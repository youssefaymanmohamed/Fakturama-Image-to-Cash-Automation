from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.automation.fakturama_app import FakturamaApp
from src.automation.uia_wrapper import UIAError, UIAWrapper


@pytest.mark.parametrize('width,height,enabled,offscreen', [
    (0, 20, True, False), (20, 0, True, False),
    (20, 20, False, False), (20, 20, True, True),
])
def test_direct_input_must_be_interactable(width, height, enabled, offscreen):
    control = Mock(ControlTypeName='EditControl', IsEnabled=enabled, IsOffscreen=offscreen)
    control.BoundingRectangle.width.return_value = width
    control.BoundingRectangle.height.return_value = height
    with pytest.raises(UIAError):
        UIAWrapper.__new__(UIAWrapper).find_input_for_label(control)


def test_nonempty_expected_value_never_matches_empty_readback():
    assert not UIAWrapper.__new__(UIAWrapper)._values_match('PO000021', '')


def test_invalid_date_is_not_replaced_with_today():
    uia = Mock()
    uia.find_by_name.side_effect = UIAError('missing date input')
    app = FakturamaApp(uia)
    with pytest.raises((ValueError, UIAError)):
        app.set_order_date('not-a-date')


def test_date_failure_does_not_emit_success_milestone():
    uia = Mock()
    uia.find_by_name.side_effect = UIAError('missing date input')
    app = FakturamaApp(uia)
    with pytest.raises(UIAError):
        app.set_order_date(datetime(2025, 3, 15, 12, 0))
    assert app.milestones == []


def test_price_mode_is_scoped_to_selected_editor_and_verified():
    uia = Mock()
    body = Mock()
    combo = Mock(Name='')
    uia.active_editor.return_value = {'body': body}
    uia.find_all_by_type.return_value = [combo]
    uia.get_value.side_effect = ['Gross', 'Net']
    app = FakturamaApp(uia)
    app._milestone = Mock()

    app.set_price_mode_net()

    uia.find_all_by_type.assert_called_once_with(
        'ComboBoxControl', parent=body, max_depth=18,
    )
    uia.select_combo_verified.assert_called_once_with(
        combo, 'Net', combo_name='PriceMode',
    )


def test_price_mode_missing_is_a_failure_not_silent_success():
    uia = Mock()
    uia.active_editor.return_value = {'body': Mock()}
    uia.find_all_by_type.return_value = []
    with pytest.raises(UIAError, match='price mode'):
        FakturamaApp(uia).set_price_mode_net()


def test_paid_invoice_does_not_toggle_checked_checkbox_off():
    uia = Mock()
    body = Mock()
    paid = Mock(Name='paid')
    paid.BoundingRectangle.top = 700
    paid.BoundingRectangle.left = 800
    paid.GetTogglePattern.return_value.ToggleState = 1
    date_edit = Mock(Name='')
    date_edit.BoundingRectangle.top = 700
    date_edit.BoundingRectangle.left = 500
    value_edit = Mock(Name='Value')
    uia.active_editor.return_value = {'kind': 'Invoice', 'body': body}
    uia.find_by_name.side_effect = [paid, value_edit]
    uia.find_all_by_type.return_value = [date_edit]
    uia.is_interactable.return_value = True
    uia.get_value.side_effect = lambda control: (
        'Mar 20, 2025' if control is date_edit else '$276.97'
    )
    uia._values_match.return_value = True
    app = FakturamaApp(uia)
    app._milestone = Mock()

    app.set_invoice_payment('', True, '20.03.2025', '276.97')

    uia.click.assert_not_called()
    uia.set_swt_date_verified.assert_called_once_with(date_edit, '20.03.2025')
    assert app._invoice_payment_verified == {
        'method': True, 'paid': True, 'date': True, 'value': True,
    }


def test_order_documents_verification_uses_copied_row_values():
    uia = Mock()
    uia._values_match.return_value = True
    app = FakturamaApp(uia)
    app._saved_editor = {'kind': 'Order', 'number': 'PO000019'}
    app._read_documents_row = Mock(return_value={
        'number': 'PO000019',
        'date': 'Sat Mar 15 00:00:00 EET 2025',
        'cust_ref': 'PO-2025-0042',
        'state': 'COMMAND_ORDER_PENDING',
        'total': '276.97',
    })
    app._milestone = Mock(return_value=Path('evidence.png'))
    order = Mock(
        external_reference='PO-2025-0042', total_gross='276.97',
        order_date=date(2025, 3, 15),
    )

    result = app.verify_order_in_documents(order)

    assert result.all_ok
    assert result.doc_number == 'PO000019'
    app._read_documents_row.assert_called_once_with('PO000019')


def test_order_documents_readback_failure_keeps_specific_reason():
    uia = Mock()
    app = FakturamaApp(uia)
    app._saved_editor = {'kind': 'Order', 'number': 'PO000026'}
    app._read_documents_row = Mock(
        side_effect=UIAError("Expected one Documents row for 'PO000026' within 6s")
    )

    with pytest.raises(UIAError, match='PO000026.*within 6s'):
        app.verify_order_in_documents(Mock())
