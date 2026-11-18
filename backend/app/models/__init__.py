"""All database models. SMA-28.

Importing this package registers every table on Base.metadata, which Alembic's
env.py needs to compare models with the database.
"""

from app.models.agent_action import AgentAction
from app.models.conversation import Conversation, Message
from app.models.document import Chunk, Document, conversation_documents
from app.models.llm_call import LLMCall
from app.models.note import Note
from app.models.task import Task
from app.models.user import User

__all__ = [
    "AgentAction",
    "Chunk",
    "Conversation",
    "Document",
    "LLMCall",
    "Message",
    "Note",
    "Task",
    "User",
    "conversation_documents",
]
