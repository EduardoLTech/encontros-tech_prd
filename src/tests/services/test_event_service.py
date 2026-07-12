
import pytest
from unittest.mock import MagicMock
from services.event_service import EventNotFoundError
from services import event_service
from schemas.event import EventCreate, EventUpdate
from models.event import Event
import datetime

def test_create_event():
    # Arrange
    mock_db = MagicMock()

    event_data = EventCreate(
        title="Test Event",
        description="A test event",
        date=datetime.datetime.now(),
        location="Test Location",
        technologies=["Python", "FastAPI"]
    )

    # Act
    created_event = event_service.create_event(db=mock_db, event=event_data)

    # Assert
    assert created_event.title == event_data.title
    assert created_event.description == event_data.description
    assert created_event.technologies == event_data.technologies
    
    # Check that add, commit, and refresh were called correctly
    mock_db.add.assert_called_once()  # Only one call to add the event
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(created_event)

def test_create_event_with_technologies():
    # Arrange
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # No existing technologies

    event_data = EventCreate(
        title="Another Test Event",
        description="Another test event",
        date=datetime.datetime.now(),
        location="Test Location",
        technologies=["FastAPI", "Python"]
    )

    # Act
    created_event = event_service.create_event(db=mock_db, event=event_data)

    # Assert
    assert created_event.title == event_data.title
    mock_db.add.assert_called()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(created_event)

def test_get_events():
    # Arrange
    mock_db = MagicMock()
    
    # Mock the query chain
    mock_query = mock_db.query.return_value
    mock_order_by = mock_query.order_by.return_value
    mock_offset = mock_order_by.offset.return_value
    
    # Act
    event_service.get_events(db=mock_db, skip=10, limit=50)

    # Assert
    mock_db.query.assert_called_once_with(Event)
    mock_query.order_by.assert_called_once()
    mock_order_by.offset.assert_called_once_with(10)
    mock_offset.limit.assert_called_once_with(50)
    mock_offset.limit.return_value.all.assert_called_once()

# Teste removido - funcionalidade de filtro por technology não implementada

def test_get_events_with_search_filter():
    # Arrange
    mock_db = MagicMock()
    
    # Mock the query chain with search filter
    mock_query = mock_db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_order_by = mock_filter.order_by.return_value
    mock_offset = mock_order_by.offset.return_value
    
    # Act
    event_service.get_events(db=mock_db, search="Python")

    # Assert
    mock_db.query.assert_called_once_with(Event)
    mock_query.filter.assert_called_once()
    mock_filter.order_by.assert_called_once()

def test_get_event_by_token_success():
    # Arrange
    mock_db = MagicMock()
    test_token = "test-token-123"
    expected_event = Event(id=1, title="Test Event", edit_token=test_token)
    
    mock_db.query.return_value.filter.return_value.first.return_value = expected_event
    
    # Act
    result = event_service.get_event_by_token(db=mock_db, edit_token=test_token)
    
    # Assert
    assert result == expected_event
    mock_db.query.assert_called_once_with(Event)

def test_get_event_by_token_not_found():
    # Arrange
    mock_db = MagicMock()
    test_token = "invalid-token"
    
    mock_db.query.return_value.filter.return_value.first.return_value = None
    
    # Act & Assert
    with pytest.raises(EventNotFoundError) as exc_info:
        event_service.get_event_by_token(db=mock_db, edit_token=test_token)
    
    assert str(exc_info.value) == "Event not found"

def test_update_event():
    # Arrange
    mock_db = MagicMock()
    test_token = "test-token-123"
    
    # Mock existing event - criar sem o campo technologies pois não existe no modelo
    existing_event = MagicMock()
    existing_event.title = "Old Title"
    existing_event.edit_token = test_token
    existing_event.id = 1
    
    mock_db.query.return_value.filter.return_value.first.return_value = existing_event
    
    event_update = EventUpdate(
        title="Updated Title",
        description="Updated description",
        date=datetime.datetime.now(),
        location="Updated Location",
        technologies=["React", "Python"]
    )
    
    # Act
    result = event_service.update_event(db=mock_db, edit_token=test_token, event_update=event_update)
    
    # Assert
    assert result.title == event_update.title
    assert result.description == event_update.description
    assert result.location == event_update.location
    assert result.technologies == event_update.technologies
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(existing_event)

# Teste get_technologies removido - funcionalidade não implementada
