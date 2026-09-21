"""Save must prove a transition on the target editor, not absence of errors."""
from unittest.mock import Mock

import pytest

from src.automation.uia_wrapper import UIAError, UIAWrapper


def state(title='*New Order', body=10, number='AU00001'):
    return dict(title=title, body_handle=body, number=number,
                identity=('Order', number), kind='Order', folder=Mock(),
                body=Mock(), tab=Mock())


@pytest.fixture
def wrapper(monkeypatch):
    u = UIAWrapper.__new__(UIAWrapper)
    monkeypatch.setattr('src.automation.uia_wrapper.ensure_desktop_and_com', lambda: None)
    u._prepare_editor_save = Mock()
    u._dispatch_save = Mock()
    u._save_diagnostics = Mock(return_value={'focus': 'Edit', 'save_enabled': True})
    return u


def test_renamed_target_is_saved_without_saving_other_dirty_tabs(wrapper):
    wrapper.active_editor = Mock(side_effect=[state(), state('AU00001')])
    result = wrapper.save_active_editor(timeout=.01)
    assert result['title'] == 'AU00001'
    assert wrapper._dispatch_save.call_count == 1


def test_clean_editor_is_idempotent(wrapper):
    wrapper.active_editor = Mock(return_value=state('AU00001'))
    assert wrapper.save_active_editor(timeout=.01)['number'] == 'AU00001'
    wrapper._dispatch_save.assert_not_called()


@pytest.mark.parametrize('title', ['New Order', '*New Order'])
def test_missing_proposed_number_rejects_incomplete_editor(wrapper, title):
    wrapper.active_editor = Mock(return_value=state(title, number=''))
    with pytest.raises(UIAError, match='number|incomplete'):
        wrapper.save_active_editor(timeout=.01)
    wrapper._dispatch_save.assert_not_called()


def test_disposed_editor_is_not_success(wrapper):
    wrapper.active_editor = Mock(side_effect=[state(), UIAError('disposed')])
    with pytest.raises(UIAError, match='inconclusive|disposed'):
        wrapper.save_active_editor(timeout=.01)


def test_recreated_editor_requires_matching_document_identity(wrapper):
    wrapper.active_editor = Mock(side_effect=[state(), state('AU00001', body=20)])
    assert wrapper.save_active_editor(timeout=.01)['body_handle'] == 20


def test_switch_to_another_clean_document_is_not_success(wrapper):
    wrapper.active_editor = Mock(side_effect=[state(), state('AU00002', body=20, number='AU00002')])
    with pytest.raises(UIAError, match='identity|target|inconclusive'):
        wrapper.save_active_editor(timeout=.01)


def test_ignored_save_stays_a_failure(wrapper):
    wrapper.active_editor = Mock(return_value=state())
    with pytest.raises(UIAError, match='dirty'):
        wrapper.save_active_editor(timeout=.01)


def test_dirty_renamed_editor_is_not_success(wrapper):
    wrapper.active_editor = Mock(side_effect=[state()] + [state('*AU00001')]*20)
    with pytest.raises(UIAError, match='dirty'):
        wrapper.save_active_editor(timeout=.01)
