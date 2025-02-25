"""
Repositories for database operations.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, TypeVar, Generic, Type

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import cast, String
from sqlalchemy.dialects.postgresql import JSONB

from src.db.models import User, Session as DbSession, Memory, Agent, ChatMessage

# Configure logging
logger = logging.getLogger("src.db.repositories")

# Generic type for models
T = TypeVar('T')

class BaseRepository(Generic[T]):
    """Base repository for database operations."""
    
    def __init__(self, db: Session, model: Type[T]):
        self.db = db
        self.model = model
    
    def get(self, id: Any) -> Optional[T]:
        """Get entity by ID."""
        return self.db.query(self.model).filter(self.model.id == id).first()
    
    def list(self, **filters) -> List[T]:
        """List entities with optional filters."""
        query = self.db.query(self.model)
        for key, value in filters.items():
            if hasattr(self.model, key):
                query = query.filter(getattr(self.model, key) == value)
        return query.all()
    
    def add(self, entity: T) -> T:
        """Add a new entity to the database."""
        # Log entity attributes for debugging
        if hasattr(entity, 'id'):
            attr_dict = {c.name: getattr(entity, c.name) 
                        for c in entity.__table__.columns 
                        if c.name not in ['raw_payload'] and hasattr(entity, c.name)}
            logger.info(f"Adding {entity.__class__.__name__} to DB: {attr_dict}")
        
        self.db.add(entity)
        return entity
    
    def create(self, **data) -> T:
        """Create a new entity."""
        # Generate UUID for string IDs if not provided
        if 'id' not in data and hasattr(self.model, 'id'):
            # Check if the ID column is String type (needs UUID)
            id_column = self.model.__table__.columns.get('id')
            if id_column is not None and isinstance(id_column.type, String):
                data['id'] = str(uuid.uuid4())
        
        # Log creation data for debugging
        log_data = {k: v for k, v in data.items() if k != 'raw_payload'}  # Skip raw payload to avoid huge logs
        logger.info(f"Creating {self.model.__name__} with data: {log_data}")
        
        entity = self.model(**data)
        return self.add(entity)
    
    def update(self, id: Any, **data) -> Optional[T]:
        """Update an entity."""
        entity = self.get(id)
        if not entity:
            return None
        
        for key, value in data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        
        # Set updated_at if the entity has this attribute
        if hasattr(entity, 'updated_at'):
            entity.updated_at = datetime.now(timezone.utc)
        
        self.db.flush()
        return entity
    
    def delete(self, id: Any) -> bool:
        """Delete an entity."""
        entity = self.get(id)
        if not entity:
            return False
        
        self.db.delete(entity)
        self.db.flush()
        return True

class UserRepository(BaseRepository[User]):
    """Repository for User operations."""
    
    def __init__(self, db: Session):
        super().__init__(db, User)
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return self.db.query(User).filter(User.email == email).first()
    
    def get_by_phone(self, phone_number: str) -> Optional[User]:
        """Get user by phone number."""
        return self.db.query(User).filter(User.phone_number == phone_number).first()
    
    def get_by_whatsapp_id(self, whatsapp_id: str) -> Optional[User]:
        """Get user by WhatsApp ID stored in user_data."""
        # For PostgreSQL JSONB we need to use the containment operator (@>)
        # This checks if the user_data column contains the specified JSON structure
        
        # Create a JSON object to check for containment
        json_to_check = {"whatsapp_id": whatsapp_id}
        
        # Query users where the user_data JSONB contains our JSON object
        users = self.db.query(User).filter(
            User.user_data.cast(JSONB).contains(json_to_check)
        ).all()
        
        # Return the first matching user, if any
        return users[0] if users else None
    
    def extract_phone_from_whatsapp_id(self, whatsapp_id: str) -> str:
        """Extract phone number from WhatsApp ID."""
        if '@' in whatsapp_id:
            return whatsapp_id.split('@')[0]
        return whatsapp_id
    
    def get_or_create_by_whatsapp(self, whatsapp_id: str) -> User:
        """Get or create a user by WhatsApp ID."""
        # First try to find by phone number (extracted from WhatsApp ID)
        phone_number = self.extract_phone_from_whatsapp_id(whatsapp_id)
        user = self.get_by_phone(phone_number)
        
        if user:
            # If found by phone but WhatsApp ID not stored, update it
            if not user.user_data or 'whatsapp_id' not in user.user_data:
                user.user_data = user.user_data or {}
                user.user_data['whatsapp_id'] = whatsapp_id
                user.user_data['source'] = 'whatsapp'
                self.db.flush()
            return user
        
        # Next try to find by WhatsApp ID in user_data
        user = self.get_by_whatsapp_id(whatsapp_id)
        
        if not user:
            # Create new user with both phone_number and WhatsApp ID
            user = self.create(
                phone_number=phone_number,
                user_data={
                    "whatsapp_id": whatsapp_id,
                    "source": "whatsapp"
                }
            )
            logger.info(f"Created new user with WhatsApp ID: {whatsapp_id} and phone: {phone_number}")
        
        return user

class SessionRepository(BaseRepository[DbSession]):
    """Repository for Session operations."""
    
    def __init__(self, db: Session):
        super().__init__(db, DbSession)
        # Get session ID prefix from environment
        from src.config import config
        import os
        self.session_id_prefix = os.getenv("AGENT_SESSION_ID_PREFIX", "")
    
    def get_latest_for_user(self, user_id: str) -> Optional[DbSession]:
        """Get the latest session for a user."""
        return self.db.query(DbSession).filter(
            DbSession.user_id == user_id
        ).order_by(DbSession.created_at.desc()).first()
    
    def get_or_create_for_user(self, user_id: str, platform: str) -> DbSession:
        """Get the latest session for a user or create a new one."""
        # Get the most recent session for this user
        session = self.get_latest_for_user(user_id)
        
        # If no session exists, create a new one
        if not session:
            # Generate prefixed session ID
            session_id = f"{self.session_id_prefix}{str(uuid.uuid4())}"
            
            session = self.create(
                id=session_id,
                user_id=user_id,
                platform=platform
            )
            logger.info(f"Created new session for user: {user_id}")
        
        return session

class ChatMessageRepository(BaseRepository[ChatMessage]):
    """Repository for ChatMessage operations."""
    
    def __init__(self, db: Session):
        super().__init__(db, ChatMessage)
    
    def get_by_session(self, session_id: str, limit: int = 50) -> List[ChatMessage]:
        """Get messages for a session with optional limit."""
        return self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.message_timestamp.asc()).limit(limit).all()
    
    def create_from_whatsapp(self, session_id: str, user_id: Any, whatsapp_message: Dict[str, Any]) -> ChatMessage:
        """Create a chat message from a WhatsApp message."""
        # Extract key information from WhatsApp message
        data = whatsapp_message.get('data', {})
        key = data.get('key', {})
        message_id = key.get('id', str(uuid.uuid4()))
        
        # Log the user_id for debugging
        logger.info(f"Creating WhatsApp message with user_id: {user_id} (type: {type(user_id).__name__})")
        
        # Message content and type
        message_content = data.get('message', {})
        
        # Determine message type and content
        message_type = None
        text_content = None
        media_url = None
        mime_type = None
        
        # Extract based on message structure
        if 'conversation' in message_content:
            message_type = 'text'
            text_content = message_content.get('conversation', '')
        elif 'extendedTextMessage' in message_content:
            message_type = 'text'
            text_content = message_content.get('extendedTextMessage', {}).get('text', '')
        elif 'imageMessage' in message_content:
            message_type = 'image'
            media_url = message_content.get('imageMessage', {}).get('url', '')
            mime_type = message_content.get('imageMessage', {}).get('mimetype', '')
            text_content = message_content.get('imageMessage', {}).get('caption', '')
        elif 'audioMessage' in message_content:
            message_type = 'audio'
            media_url = message_content.get('audioMessage', {}).get('url', '')
            mime_type = message_content.get('audioMessage', {}).get('mimetype', '')
        
        # Fallback for unknown message types
        if not message_type:
            message_type = 'unknown'
            logger.warning(f"Unknown message type: {message_content}")
        
        # Get timestamp
        timestamp_ms = data.get('messageTimestamp', 0) * 1000
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000.0)
        
        # Create the message
        return self.create(
            id=message_id,
            session_id=session_id,
            user_id=user_id,
            role='user',
            text_content=text_content,
            media_url=media_url,
            mime_type=mime_type,
            message_type=message_type,
            raw_payload=whatsapp_message,
            message_timestamp=timestamp
        )

class AgentRepository(BaseRepository[Agent]):
    """Repository for Agent operations."""
    
    def __init__(self, db: Session):
        super().__init__(db, Agent)
    
    def get_first(self) -> Optional[Agent]:
        """Get the first agent (used when there's only one agent)."""
        return self.db.query(Agent).first()
    
    def get_active_agent(self, agent_type: str = "whatsapp") -> Optional[Agent]:
        """Get the active agent of a specific type."""
        return self.db.query(Agent).filter(
            Agent.type == agent_type,
            Agent.active == True
        ).first()
    
    def create_agent_response(self, session_id: str, user_id: Any, agent_id: str, 
                             text_content: str, tool_calls: Optional[Dict] = None, 
                             tool_outputs: Optional[Dict] = None) -> ChatMessage:
        """Create an agent response message."""
        # Log the user_id for debugging
        logger.info(f"Creating agent response with user_id: {user_id} (type: {type(user_id).__name__})")
        
        return ChatMessageRepository(self.db).create(
            session_id=session_id,
            user_id=user_id,  # No conversion needed, passing as is
            agent_id=agent_id,
            role='assistant',
            text_content=text_content,
            tool_calls=tool_calls,
            tool_outputs=tool_outputs,
            message_type='text',
            message_timestamp=datetime.now(timezone.utc)
        )

class MemoryRepository(BaseRepository[Memory]):
    """Repository for Memory operations."""
    
    def __init__(self, db: Session):
        super().__init__(db, Memory)
    
    def get_user_memories(self, user_id: str, limit: int = 10) -> List[Memory]:
        """Get memories for a user with optional limit."""
        return self.db.query(Memory).filter(
            Memory.user_id == user_id
        ).order_by(Memory.created_at.desc()).limit(limit).all() 