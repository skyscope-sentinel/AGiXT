import os
import base64
import asyncio
from fastapi import APIRouter, HTTPException, Depends, Header
from ApiClient import Agent, verify_api_key, get_api_client, WORKERS, is_admin
from typing import Dict, Any, List
from Websearch import Websearch
from XT import AGiXT
from Memories import Memories
from Conversations import Conversations
from readers.github import GithubReader
from readers.file import FileReader
from readers.arxiv import ArxivReader
from readers.youtube import YoutubeReader
from datetime import datetime
from Models import (
    AgentMemoryQuery,
    TextMemoryInput,
    FileInput,
    UrlInput,
    GitHubInput,
    ArxivInput,
    YoutubeInput,
    ResponseMessage,
    Dataset,
    FinetuneAgentModel,
    ExternalSource,
    UserInput,
    FeedbackInput,
)
import logging
from Globals import getenv

logging.basicConfig(
    level=getenv("LOG_LEVEL"),
    format=getenv("LOG_FORMAT"),
)
app = APIRouter()


@app.post(
    "/api/agent/{agent_name}/memory/{collection_number}/query",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def query_memories(
    agent_name: str,
    memory: AgentMemoryQuery,
    collection_number="0",
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> Dict[str, Any]:
    ApiClient = get_api_client(authorization=authorization)
    agent_config = Agent(
        agent_name=agent_name, user=user, ApiClient=ApiClient
    ).get_agent_config()
    memories = await Memories(
        agent_name=agent_name,
        agent_config=agent_config,
        collection_number=str(collection_number),
        ApiClient=ApiClient,
        user=user,
    ).get_memories_data(
        user_input=memory.user_input,
        limit=memory.limit,
        min_relevance_score=memory.min_relevance_score,
    )
    return {"memories": memories}


# Export all agent memories
@app.get(
    "/api/agent/{agent_name}/memory/export",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def export_agent_memories(
    agent_name: str, user=Depends(verify_api_key), authorization: str = Header(None)
) -> Dict[str, Any]:
    ApiClient = get_api_client(authorization=authorization)
    agent_config = Agent(
        agent_name=agent_name, user=user, ApiClient=ApiClient
    ).get_agent_config()
    memories = await Memories(
        agent_name=agent_name, agent_config=agent_config, ApiClient=ApiClient, user=user
    ).export_collections_to_json()
    return {"memories": memories}


@app.post(
    "/api/agent/{agent_name}/memory/import",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def import_agent_memories(
    agent_name: str,
    memories: List[dict],
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    ApiClient = get_api_client(authorization=authorization)
    agent_config = Agent(
        agent_name=agent_name, user=user, ApiClient=ApiClient
    ).get_agent_config()
    await Memories(
        agent_name=agent_name, agent_config=agent_config, ApiClient=ApiClient, user=user
    ).import_collections_from_json(memories)
    return ResponseMessage(message="Memories imported.")


@app.post(
    "/api/agent/{agent_name}/learn/text",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def learn_text(
    agent_name: str,
    data: TextMemoryInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    ApiClient = get_api_client(authorization=authorization)
    agent_config = Agent(
        agent_name=agent_name, user=user, ApiClient=ApiClient
    ).get_agent_config()
    if len(data.collection_number) > 4:
        conversation = Conversations(
            conversation_name=data.collection_number, user=user
        )
        collection_number = conversation.get_conversation_id()
    else:
        collection_number = str(data.collection_number)
    memory = Memories(
        agent_name=agent_name,
        agent_config=agent_config,
        collection_number=collection_number,
        ApiClient=ApiClient,
        user=user,
    )
    await memory.write_text_to_memory(
        user_input=data.user_input, text=data.text, external_source="user input"
    )
    return ResponseMessage(
        message="Agent learned the content from the text assocated with the user input."
    )


@app.post(
    "/api/agent/{agent_name}/learn/file",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def learn_file(
    agent_name: str,
    file: FileInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    timestamp = datetime.now().strftime("%Y-%m-%d")
    agent = AGiXT(
        user=user,
        agent_name=agent_name,
        api_key=authorization,
        conversation_name=f"{agent_name} Training on {timestamp}",
        collection_id=file.collection_number,
    )
    file.file_name = os.path.basename(file.file_name)
    file_path = os.path.normpath(
        os.path.join(agent.agent_workspace, file.collection_number, file.file_name)
    )
    logging.info(f"File path: {file_path}")
    if not file_path.startswith(agent.agent_workspace):
        raise Exception("Path given not allowed")
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    try:
        file_content = base64.b64decode(file.file_content)
    except:
        file_content = file.file_content.encode("utf-8")
    with open(file_path, "wb") as f:
        f.write(file_content)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"File {file.file_name} uploaded on {timestamp}.")
    logging.info(
        f"URL of file: {agent.outputs}/{file.collection_number}/{file.file_name}"
    )
    response = await agent.learn_from_file(
        file_url=f"{agent.outputs}/{file.collection_number}/{file.file_name}",
        file_name=file.file_name,
        user_input=f"File {file.file_name} uploaded on {timestamp}.",
        collection_id=str(file.collection_number),
    )
    agent.conversation.log_interaction(
        role=agent_name,
        message=f"File [{file.file_name}]({agent.outputs}/{file.collection_number}/{file.file_name}) learned on {timestamp} to collection `{file.collection_number}`.",
    )
    return ResponseMessage(message=response)


@app.post(
    "/api/agent/{agent_name}/learn/url",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def learn_url(
    agent_name: str,
    url: UrlInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    timestamp = datetime.now().strftime("%Y-%m-%d")
    ApiClient = get_api_client(authorization=authorization)
    agent = Agent(agent_name=agent_name, user=user, ApiClient=ApiClient)
    url.url = url.url.replace(" ", "%20")
    websearch = Websearch(
        collection_number=url.collection_number,
        agent=agent,
        user=user,
        ApiClient=ApiClient,
    )
    conversation_name = f"{agent_name} Training on {timestamp}"
    response = await websearch.scrape_websites(
        user_input=f"I am browsing {url.url} and collecting data from it to learn more.",
        conversation_name=conversation_name,
    )
    c = Conversations(conversation_name=conversation_name, user=user)
    c.log_interaction(
        role=agent_name,
        message=f"URL [{url.url}]({url.url}) learned on {timestamp} to collection `{url.collection_number}`.",
    )
    return ResponseMessage(message=response)


@app.post(
    "/api/agent/{agent_name}/learn/github",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def learn_github_repo(
    agent_name: str,
    git: GitHubInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    ApiClient = get_api_client(authorization=authorization)
    agent_config = Agent(
        agent_name=agent_name, user=user, ApiClient=ApiClient
    ).get_agent_config()
    await GithubReader(
        agent_name=agent_name,
        agent_config=agent_config,
        collection_number=str(git.collection_number),
        use_agent_settings=git.use_agent_settings,
        ApiClient=ApiClient,
        user=user,
    ).write_github_repository_to_memory(
        github_repo=git.github_repo,
        github_user=git.github_user,
        github_token=git.github_token,
        github_branch=git.github_branch,
    )
    return ResponseMessage(
        message="Agent learned the content from the GitHub Repository."
    )


@app.post(
    "/api/agent/{agent_name}/learn/arxiv",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def learn_arxiv(
    agent_name: str,
    arxiv_input: ArxivInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    ApiClient = get_api_client(authorization=authorization)
    agent_config = Agent(
        agent_name=agent_name, user=user, ApiClient=ApiClient
    ).get_agent_config()
    await ArxivReader(
        agent_name=agent_name,
        agent_config=agent_config,
        collection_number=str(arxiv_input.collection_number),
        ApiClient=ApiClient,
    ).write_arxiv_articles_to_memory(
        query=arxiv_input.query,
        article_ids=arxiv_input.article_ids,
        max_articles=arxiv_input.max_results,
    )
    return ResponseMessage(message="Agent learned the content from the arXiv articles.")


@app.post(
    "/api/agent/{agent_name}/learn/youtube",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def learn_youtube(
    agent_name: str,
    youtube_input: YoutubeInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    ApiClient = get_api_client(authorization=authorization)
    agent_config = Agent(
        agent_name=agent_name, user=user, ApiClient=ApiClient
    ).get_agent_config()
    await YoutubeReader(
        agent_name=agent_name,
        agent_config=agent_config,
        collection_number=str(youtube_input.collection_number),
        ApiClient=ApiClient,
    ).write_youtube_captions_to_memory(video_id=youtube_input.video_id)
    return ResponseMessage(message="Agent learned the content from the YouTube video.")


@app.post(
    "/api/agent/{agent_name}/reader/{reader_name}",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def agent_reader(
    agent_name: str,
    reader_name: str,
    data: dict,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    ApiClient = get_api_client(authorization=authorization)
    agent = Agent(agent_name=agent_name, user=user, ApiClient=ApiClient)
    agent_config = agent.AGENT_CONFIG
    collection_number = (
        str(data["collection_number"]) if "collection_number" in data else "0"
    )
    if reader_name == "file":
        response = await FileReader(
            agent_name=agent_name,
            agent_config=agent_config,
            collection_number=collection_number,
            ApiClient=ApiClient,
            user=user,
        ).write_file_to_memory(file_path=data["file_path"])
    elif reader_name == "website":
        response = await Websearch(
            collection_number=collection_number,
            agent=agent,
            user=user,
            ApiClient=ApiClient,
        ).get_web_content(url=data["url"])
    elif reader_name == "github":
        response = await GithubReader(
            agent_name=agent_name,
            agent_config=agent_config,
            collection_number=collection_number,
            use_agent_settings=(
                data["use_agent_settings"] if "use_agent_settings" in data else False
            ),
            ApiClient=ApiClient,
            user=user,
        ).write_github_repository_to_memory(
            github_repo=data["github_repo"],
            github_user=data["github_user"] if "github_user" in data else None,
            github_token=data["github_token"] if "github_token" in data else None,
            github_branch=data["github_branch"] if "github_branch" in data else "main",
        )
    elif reader_name == "arxiv":
        response = await ArxivReader(
            agent_name=agent_name,
            agent_config=agent_config,
            collection_number=collection_number,
            ApiClient=ApiClient,
            user=user,
        ).write_arxiv_articles_to_memory(
            query=data["query"],
            article_ids=data["article_ids"],
            max_articles=data["max_articles"],
        )
    elif reader_name == "youtube":
        response = await YoutubeReader(
            agent_name=agent_name,
            agent_config=agent_config,
            collection_number=collection_number,
            ApiClient=ApiClient,
            user=user,
        ).write_youtube_captions_to_memory(video_id=data["video_id"])
    else:
        raise HTTPException(status_code=400, detail="Invalid reader name.")
    if response == True:
        return ResponseMessage(
            message=f"Agent learned the content from the {reader_name}."
        )
    else:
        return ResponseMessage(message=f"Agent failed to learn the content.")


@app.delete(
    "/api/agent/{agent_name}/memory",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def wipe_agent_memories(
    agent_name: str, user=Depends(verify_api_key), authorization: str = Header(None)
) -> ResponseMessage:
    if is_admin(email=user, api_key=authorization) != True:
        raise HTTPException(status_code=403, detail="Access Denied")
    ApiClient = get_api_client(authorization=authorization)
    agent = Agent(agent_name=agent_name, user=user, ApiClient=ApiClient)
    await Memories(
        agent_name=agent_name,
        agent_config=agent.AGENT_CONFIG,
        collection_number="0",
        ApiClient=ApiClient,
        user=user,
    ).wipe_memory()
    return ResponseMessage(message=f"Memories for agent {agent_name} deleted.")


@app.delete(
    "/api/agent/{agent_name}/memory/{collection_number}",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def wipe_agent_memories(
    agent_name: str,
    collection_number: str = "0",
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    if is_admin(email=user, api_key=authorization) != True:
        raise HTTPException(status_code=403, detail="Access Denied")
    ApiClient = get_api_client(authorization=authorization)
    agent = Agent(agent_name=agent_name, user=user, ApiClient=ApiClient)
    await Memories(
        agent_name=agent_name,
        agent_config=agent.AGENT_CONFIG,
        collection_number=collection_number,
        ApiClient=ApiClient,
        user=user,
    ).wipe_memory()
    return ResponseMessage(message=f"Memories for agent {agent_name} deleted.")


@app.delete(
    "/api/agent/{agent_name}/memory/{collection_number}/{memory_id}",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def delete_agent_memory(
    agent_name: str,
    collection_number: str = "0",
    memory_id="",
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    ApiClient = get_api_client(authorization=authorization)
    agent = Agent(agent_name=agent_name, user=user, ApiClient=ApiClient)
    await Memories(
        agent_name=agent_name,
        agent_config=agent.AGENT_CONFIG,
        collection_number=collection_number,
        ApiClient=ApiClient,
        user=user,
    ).delete_memory(key=memory_id)
    return ResponseMessage(
        message=f"Memory {memory_id} for agent {agent_name} deleted."
    )


# Create dataset
@app.post(
    "/api/agent/{agent_name}/memory/dataset",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
    summary="Create a dataset from the agent's memories",
)
async def create_dataset(
    agent_name: str,
    dataset: Dataset,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    if is_admin(email=user, api_key=authorization) != True:
        raise HTTPException(status_code=403, detail="Access Denied")
    batch_size = dataset.batch_size if dataset.batch_size < (int(WORKERS) - 2) else 4
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    asyncio.create_task(
        AGiXT(
            agent_name=agent_name,
            user=user,
            api_key=authorization,
            conversation_name=f"Dataset Creation on {timestamp}",
        ).create_dataset_from_memories(batch_size=batch_size)
    )
    return ResponseMessage(
        message=f"Creation of dataset {dataset.dataset_name} for agent {agent_name} started."
    )


@app.post(
    "/api/agent/{agent_name}/dpo",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
    summary="Gets a DPO response for a question",
)
async def get_dpo_response(
    agent_name: str,
    user_input: UserInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> Dict[str, Any]:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    agixt = AGiXT(
        user=user,
        agent_name=agent_name,
        api_key=authorization,
        conversation_name=f"DPO on {timestamp}",
    )
    prompt, chosen, rejected = await agixt.dpo(
        question=user_input, injected_memories=int(user_input.injected_memories)
    )
    return {
        "prompt": prompt,
        "chosen": chosen,
        "rejected": rejected,
    }


# Train model
@app.post(
    "/api/agent/{agent_name}/memory/dataset/{dataset_name}/finetune",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
    summary="Fine tune a language model with the agent's memories as a synthetic dataset",
)
async def fine_tune_model(
    agent_name: str,
    finetune: FinetuneAgentModel,
    dataset_name: str,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    if is_admin(email=user, api_key=authorization) != True:
        raise HTTPException(status_code=403, detail="Access Denied")
    from Tuning import fine_tune_llm

    ApiClient = get_api_client(authorization=authorization)
    asyncio.create_task(
        fine_tune_llm(
            agent_name=agent_name,
            dataset_name=dataset_name,
            model_name=finetune.model,
            max_seq_length=finetune.max_seq_length,
            huggingface_output_path=finetune.huggingface_output_path,
            private_repo=finetune.private_repo,
            ApiClient=ApiClient,
        )
    )
    return ResponseMessage(
        message=f"Fine-tuning of model {finetune.model_name} started. The agent's status has is now set to True, it will be set to False once the training is complete."
    )


# Delete memories from external source
@app.delete(
    "/api/agent/{agent_name}/memory/external_source",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def delete_memories_from_external_source(
    agent_name: str,
    external_source: ExternalSource,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    if is_admin(email=user, api_key=authorization) != True:
        raise HTTPException(status_code=403, detail="Access Denied")
    ApiClient = get_api_client(authorization=authorization)
    agent = Agent(agent_name=agent_name, user=user, ApiClient=ApiClient)
    await Memories(
        agent_name=agent_name,
        agent_config=agent.AGENT_CONFIG,
        collection_number=str(external_source.collection_number),
        ApiClient=ApiClient,
        user=user,
    ).delete_memories_from_external_source(
        external_source=external_source.external_source
    )
    return ResponseMessage(
        message=f"Memories from external source {external_source.external_source} for agent {agent_name} deleted."
    )


# Get unique external sources
@app.get(
    "/api/agent/{agent_name}/memory/external_sources/{collection_number}",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def get_unique_external_sources(
    agent_name: str,
    collection_number: str = "0",
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> Dict[str, Any]:
    ApiClient = get_api_client(authorization=authorization)
    agent = Agent(agent_name=agent_name, user=user, ApiClient=ApiClient)
    external_sources = await Memories(
        agent_name=agent_name,
        agent_config=agent.AGENT_CONFIG,
        collection_number=collection_number,
        ApiClient=ApiClient,
        user=user,
    ).get_external_data_sources()
    return {"external_sources": external_sources}


# RLHF endpoint
@app.post(
    "/api/agent/{agent_name}/feedback",
    tags=["Memory"],
    dependencies=[Depends(verify_api_key)],
)
async def rlhf(
    agent_name: str,
    data: FeedbackInput,
    user=Depends(verify_api_key),
    authorization: str = Header(None),
) -> ResponseMessage:
    agixt = AGiXT(
        user=user,
        agent_name=agent_name,
        api_key=authorization,
        conversation_name=data.conversation_name,
    )
    c = agixt.conversation
    if c.has_received_feedback(message=data.message):
        return ResponseMessage(
            message="Feedback already received for this interaction."
        )
    if data.positive == True:
        memory = agixt.agent_interactions.positive_feedback_memories
    else:
        memory = agixt.agent_interactions.negative_feedback_memories
    reflection = await agixt.inference(
        user_input=data.user_input,
        input_kind="positive" if data.positive == True else "negative",
        assistant_response=data.message,
        feedback=data.feedback,
        log_user_input=False,
        log_output=False,
    )
    memory_message = f"""## Feedback received from a similar interaction in the past:
### User
{data.user_input}

### Assistant
{data.message}

### Feedback from User
{data.feedback}

### Reflection on the feedback
{reflection}
"""
    await memory.write_text_to_memory(
        user_input=data.user_input,
        text=memory_message,
        external_source="reflection from user feedback",
    )
    response_message = (
        f"{'Positive' if data.positive == True else 'Negative'} feedback received."
    )
    c.log_interaction(
        role=agent_name,
        message=f"[ACTIVITY][FEEDBACK] {response_message}",
    )
    c.toggle_feedback_received(message=data.message)
    return ResponseMessage(message=response_message)
