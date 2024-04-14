"""FastAPI Backend for the Knowledge Agent."""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile
from fastapi.openapi.utils import get_openapi
from loguru import logger
from qdrant_client import models
from qdrant_client.http.models.models import UpdateResult
from starlette.responses import JSONResponse

from agent.backend.LLMStrategy import LLMContext, LLMStrategyFactory
from agent.data_model.request_data_model import (
    CustomPromptCompletion,
    EmbeddTextFilesRequest,
    EmbeddTextRequest,
    ExplainQARequest,
    Filtering,
    LLMBackend,
    LLMProvider,
    RAGRequest,
    SearchRequest,
)
from agent.data_model.response_data_model import (
    EmbeddingResponse,
    ExplainQAResponse,
    QAResponse,
    SearchResponse,
)
from agent.utils.utility import (
    combine_text_from_list,
    create_tmp_folder,
    initialize_aleph_alpha_vector_db,
    initialize_gpt4all_vector_db,
    initialize_open_ai_vector_db,
    validate_token,
)
from agent.utils.vdb import load_vec_db_conn

# add file logger for loguru
# logger.add("logs/file_{time}.log", backtrace=False, diagnose=False)
logger.info("Startup.")


def my_schema() -> dict:
    """Used to generate the OpenAPI schema.

    Returns
    -------
        FastAPI: FastAPI App
    """
    openapi_schema = get_openapi(
        title="Conversational AI API",
        version="1.0",
        description="Chat with your Documents using Conversational AI by Aleph Alpha, GPT4ALL and OpenAI.",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


# initialize the Fast API Application.
app = FastAPI(debug=True)
app.openapi = my_schema

load_dotenv()

# load the token from the environment variables, is None if not set.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ALEPH_ALPHA_API_KEY = os.environ.get("ALEPH_ALPHA_API_KEY")
logger.info("Loading REST API Finished.")


@app.get("/", tags=["root"])
def read_root() -> str:
    """Returns the welcome message.

    Returns
    -------
        str: The welcome message.
    """
    return "Welcome to the RAG Backend. Please navigate to /docs for the OpenAPI!"


def embedd_documents_wrapper(folder_name: str, service: LLMContext) -> None:
    """Call the right embedding function for the chosen backend.

    Args:
    ----
        folder_name (str): Name of the temporary folder.
        service (LLMContext): The llm context.

    Raises:
    ------
        ValueError: If an invalid LLM Provider is set.

    """
    # TODO: make file ending dynamic
    service.embed_documents(directory=folder_name, file_ending="*.pdf")


@app.post("/collection/create/{llm_provider}/{collection_name}", tags=["collection"])
def create_collection(llm_provider: LLMProvider, collection_name: str) -> JSONResponse:
    """Create a new collection in the vector database.

    Args:
    ----
        llm_provider (LLMProvider): Name of the LLM Provider
        collection_name (str): Name of the Collection
    """
    service = LLMContext(LLMStrategyFactory.get_strategy(strategy_type=llm_provider, token="", collection_name=collection_name))

    service.create_collection(name=collection_name)

    # return a success message
    return JSONResponse(content={"message": f"Collection {collection_name} created."})


@app.post("/embeddings/documents", tags=["embeddings"])
async def post_embedd_documents(llm_backend: LLMBackend, files: list[UploadFile]) -> EmbeddingResponse:
    """Uploads multiple documents to the backend.

    Args:
    ----
        llm_backend (LLMBackend): The LLM Backend.
        files (List[UploadFile], optional): Uploaded files. Defaults to File(...).

    Returns:
    -------
        JSONResponse: The response as JSON.
    """
    logger.info("Embedding Multiple Documents")

    token = validate_token(token=llm_backend.token, llm_backend=llm_backend, aleph_alpha_key=ALEPH_ALPHA_API_KEY, openai_key=OPENAI_API_KEY)
    tmp_dir = create_tmp_folder()

    llm_context = LLMContext(LLMStrategyFactory.get_strategy(strategy_type=LLMProvider.ALEPH_ALPHA, token=token, collection_name=llm_backend.collection_name))

    file_names = []

    for file in files:
        file_name = file.filename
        file_names.append(file_name)

        # Save the file to the temporary folder
        if tmp_dir is None or not Path(tmp_dir).exists():
            msg = "Please provide a temporary folder to save the files."
            raise ValueError(msg)

        if file_name is None:
            msg = "Please provide a file to save."
            raise ValueError(msg)

        with Path(tmp_dir / file_name).open("wb") as f:
            f.write(await file.read())

    embedd_documents_wrapper(folder_name=tmp_dir, service=llm_context)

    return EmbeddingResponse(status="success", files=file_names)


@app.post("/embeddings/text/", tags=["embeddings"])
async def embedd_text(embedding: EmbeddTextRequest, llm_backend: LLMBackend) -> EmbeddingResponse:
    """Embeds text in the database.

    Args:
    ----
        embedding (EmbeddTextRequest): The request parameters.
        llm_backend (LLMBackend): The LLM Backend.

    Raises:
    ------
        ValueError: If no token is provided or if no LLM provider is specified.

    Returns:
    -------
        JSONResponse: A response indicating that the text was received and saved, along with the name of the file it was saved to.
    """
    logger.info("Embedding Text")
    token = validate_token(token=llm_backend.token, llm_backend=llm_backend, aleph_alpha_key=ALEPH_ALPHA_API_KEY, openai_key=OPENAI_API_KEY)

    service = LLMContext(LLMStrategyFactory.get_strategy(strategy_type=llm_backend.llm_provider, token=token, collection_name=llm_backend.collection_name))

    service.embed_documents(text=embedding.text, file_name=embedding.file_name, seperator=embedding.seperator)

    return EmbeddingResponse(status="success", files=[embedding.file_name])


@app.post("/embeddings/texts/files", tags=["embeddings"])
async def embedd_text_files(embedding: EmbeddTextFilesRequest, llm_backend: LLMBackend) -> EmbeddingResponse:
    """Embeds text files in the database.

    Args:
    ----
        embedding (EmbeddTextFilesRequest): The request parameters.
        llm_backend (LLMBackend): The LLM Backend.

    Raises:
    ------
        ValueError: If a file does not have a valid name, if no temporary folder is provided, or if no token or LLM provider is specified.

    Returns:
    -------
        JSONResponse: A response indicating that the files were received and saved, along with the names of the files they were saved to.
    """
    logger.info("Embedding Text Files")
    tmp_dir = create_tmp_folder()

    file_names = []

    for file in embedding.files:
        file_name = file.filename
        file_names.append(file_name)

        if file_name is None:
            msg = "File does not have a valid name."
            raise ValueError(msg)

        # Save the files to the temporary folder
        if tmp_dir is None or not Path(tmp_dir).exists():
            msg = "Please provide a temporary folder to save the files."
            raise ValueError(msg)

        with Path(tmp_dir / file_name).open("wb") as f:
            f.write(await file.read())

    token = validate_token(token=llm_backend.token, llm_backend=llm_backend.llm_provider, aleph_alpha_key=ALEPH_ALPHA_API_KEY, openai_key=OPENAI_API_KEY)

    service = LLMContext(LLMStrategyFactory.get_strategy(strategy_type=llm_backend.llm_provider, token=token, collection_name=llm_backend.collection_name))

    service.embed_documents(folder=tmp_dir, aleph_alpha_token=token, seperator=embedding.seperator)

    return EmbeddingResponse(status="success", files=file_names)


@app.post("/semantic/search", tags=["search"])
def search(search: SearchRequest, llm_backend: LLMBackend, filtering: Filtering) -> list[SearchResponse]:
    """Searches for a query in the vector database.

    Args:
    ----
        search (SearchRequest): The search request.
        llm_backend (LLMBackend): The LLM Backend.
        filtering (Filtering): The Filtering Parameters.

    Raises:
    ------
        ValueError: If the LLM provider is not implemented yet.

    Returns:
    -------
        List[str]: A list of matching documents.
    """
    logger.info("Searching for Documents")
    llm_backend.token = validate_token(token=llm_backend.token, llm_backend=llm_backend.llm_provider, aleph_alpha_key=ALEPH_ALPHA_API_KEY, openai_key=OPENAI_API_KEY)

    service = LLMContext(LLMStrategyFactory.get_strategy(strategy_type=llm_backend.llm_provider, token=llm_backend.token, collection_name=llm_backend.collection_name))

    docs = service.search(search=search, filtering=filtering)

    if not docs:
        logger.info("No Documents found.")
        return JSONResponse(content={"message": "No documents found."})

    logger.info(f"Found {len(docs)} documents.")

    response = []
    for d in docs:
        score = d[1]
        text = d[0].page_content
        page = d[0].metadata["page"]
        source = d[0].metadata["source"]
        response.append(SearchResponse(text=text, page=page, source=source, score=score))

    return response


@app.post("/rag", tags=["rag"])
def question_answer(rag: RAGRequest, llm_backend: LLMBackend, filtering: Filtering) -> QAResponse:
    """Answer a question based on the documents in the database.

    Args:
    ----
        rag (RAGRequest): The request parameters.
        llm_backend (LLMBackend): The LLM Backend.
        filtering (Filtering): The Filtering Parameters.

    Raises:
    ------
        ValueError: Error if no query or token is provided.

    Returns:
    -------
        Tuple: Answer, Prompt and Meta Data
    """
    logger.info("Answering Question")
    # if the query is not provided, raise an error
    if rag.search.query is None:
        msg = "Please provide a Question."
        raise ValueError(msg)

    token = validate_token(token=llm_backend.token, llm_backend=llm_backend.llm_provider, aleph_alpha_key=ALEPH_ALPHA_API_KEY, openai_key=OPENAI_API_KEY)

    service = LLMContext(LLMStrategyFactory.get_strategy(strategy_type=llm_backend.llm_provider, token=token, collection_name=llm_backend.collection_name))
    # summarize the history
    if rag.history:
        # combine the texts
        # TODO: adopt to dict
        text = combine_text_from_list(rag.history)
        service.summarize_text(text=text, token="")

    answer, prompt, meta_data = service.rag(rag=rag, llm_backend=llm_backend, filtering=filtering)

    return QAResponse(answer=answer, prompt=prompt, meta_data=meta_data)


@app.post("/explanation/explain-qa", tags=["explanation"])
def explain_question_answer(explain_request: ExplainQARequest, llm_backend: LLMBackend) -> ExplainQAResponse:
    """Answer a question & explains it based on the documents in the database. This only works with Aleph Alpha.

    This uses the normal qa but combines it with the explain function.

    Args:
    ----
        explain_request (ExplainQARequest): The Explain Requesat
        llm_backend (LLMBackend): The LLM Backend.

    Raises:
    ------
        ValueError: Error if no query or token is provided.

    Returns:
    -------
        Tuple: Answer, Prompt and Meta Data

    """
    logger.info("Answering Question and Explaining it.")
    # if the query is not provided, raise an error
    if explain_request.rag_request.search.query is None:
        msg = "Please provide a Question."
        raise ValueError(msg)

    explain_request.rag_request.search.llm_backend.token = validate_token(
        token=explain_request.rag_request.search.llm_backend.token,
        llm_backend=explain_request.rag_request.search.llm_backend.llm_provider,
        aleph_alpha_key=ALEPH_ALPHA_API_KEY,
        openai_key=OPENAI_API_KEY,
    )

    service = LLMContext(
        LLMStrategyFactory.get_strategy(strategy_type=llm_backend.llm_provider, token=search.llm_backend.token, collection_name=llm_backend.collection_name)
    )

    documents = service.search(explain_request.rag_request.search)

    # call the qa function
    explanation, score, text, answer, meta_data = service.explain_qa(
        query=explain_request.rag_request.search.query,
        explain_threshold=explain_request.explain_threshold,
        document=documents,
        aleph_alpha_token=explain_request.rag_request.search.llm_backend.token,
    )

    return ExplainQAResponse(explanation=explanation, score=score, text=text, answer=answer, meta_data=meta_data)


# @app.post("/process_document", tags=["custom"])
# async def process_document(files: list[UploadFile] = File(...), llm_backend: str = "aa", token: str | None = None, document_type: str = "invoice") -> None:
#     """Process a document.

#     Args:
#     ----
#         files (UploadFile): _description_
#         llm_backend (str, optional): _description_. Defaults to "openai".
#         token (Optional[str], optional): _description_. Defaults to None.
#         type (str, optional): _description_. Defaults to "invoice".

#     Returns:
#     -------
#         JSONResponse: _description_
#     """
#     logger.info("Processing Document")
#     token = validate_token(token=token, llm_backend=llm_backend, aleph_alpha_key=ALEPH_ALPHA_API_KEY, openai_key=OPENAI_API_KEY)

#     # Create a temporary folder to save the files
#     tmp_dir = create_tmp_folder()

#     file_names = []

#     for file in files:
#         file_name = file.filename
#         file_names.append(file_name)

#         # Save the file to the temporary folder
#         if tmp_dir is None or not Path(tmp_dir).exists():
#             msg = "Please provide a temporary folder to save the files."
#             raise ValueError(msg)

#         if file_name is None:
#             msg = "Please provide a file to save."
#             raise ValueError(msg)

#         with Path(tmp_dir / file_name).open() as f:
#             f.write(await file.read())

#     process_documents_aleph_alpha(folder=tmp_dir, token=token, type=document_type)

#     logger.info(f"Found {len(documents)} documents.")
#     return documents


@app.post("/llm/completion/custom", tags=["custom"])
async def custom_prompt_llm(request: CustomPromptCompletion) -> str:
    """The method sents a custom completion request to the LLM Provider.

    Args:
    ----
        request (CustomPromptCompletion): The request parameters.

    Raises:
    ------
        ValueError: If the LLM provider is not implemented yet.
    """
    logger.info("Sending Custom Completion Request")

    service = LLMContext(
        LLMStrategyFactory.get_strategy(
            strategy_type=request.search.llm_backend.llm_provider, token=request.search.llm_backend.token, collection_name=request.search.collection_name
        )
    )

    return service.generate(request.text)


@app.delete("/embeddings/delete/{llm_provider}/{page}/{source}", tags=["embeddings"])
def delete(
    page: int,
    source: str,
    llm_provider: LLMProvider = LLMProvider.OPENAI,
) -> UpdateResult:
    """Delete a Vector from the database based on the page and source.

    Args:
    ----
        page (int): The page of the Document
        source (str): The name of the Document
        llm_provider (LLMProvider, optional): The LLM Provider. Defaults to LLMProvider.OPENAI.

    Returns:
    -------
        UpdateResult: The result of the Deletion Operation from the Vector Database.
    """
    logger.info("Deleting Vector from Database")
    if llm_provider == LLMProvider.ALEPH_ALPHA:
        collection = "aleph-alpha"
    elif llm_provider == LLMProvider.OPENAI:
        collection = "openai"
    elif llm_provider == LLMProvider.GPT4ALL:
        collection = "gpt4all"
    else:
        msg = f"Unsupported LLM provider: {llm_provider}"
        raise ValueError(msg)

    qdrant_client, _ = load_vec_db_conn()

    result = qdrant_client.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.page",
                        match=models.MatchValue(value=page),
                    ),
                    models.FieldCondition(key="metadata.source", match=models.MatchValue(value=source)),
                ],
            )
        ),
    )

    logger.info("Deleted Point from Database via Metadata.")
    return result


# initialize the databases
initialize_open_ai_vector_db()
initialize_aleph_alpha_vector_db()
initialize_gpt4all_vector_db()

# for debugging useful.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
