"""El mapa de lo que prueba qué en M45: cada frase tiene un dueño, y el dueño existe (Milestone 45, Commit 12).

El Commit 12 pide invariantes y caos de punta a punta **sin duplicar** lo que M44 y los commits de M45 ya prueban. Esto
es la contabilidad de ese «sin duplicar»: cada frase del encargo apunta a la prueba (o pruebas) que la fijan, sean de
antes o de este commit.

Y no es un documento que pueda pudrirse: **este test falla si una de esas pruebas desaparece o cambia de nombre**. Si
alguien borra la prueba de «un reembolso nunca supera lo capturado», no se entera por casualidad dentro de un año: se
entera ahora, porque la frase se queda sin dueño.

La lectura es estática (`ast`): no se ejecuta nada, y no se mira el resultado de las pruebas (eso lo hace `pytest`),
solo que **existen**.
"""

import ast
from pathlib import Path

HERE = Path(__file__).parent
UNIT = HERE.parent / "unit"

#: frase → [(fichero, prueba)]. Un fichero sin carpeta es de `integration`; `unit/…` es de `unit`.
COVERAGE: dict[str, list[tuple[str, str]]] = {
    # --- Invariantes ---
    "ninguna entrada del registro sin un PaymentEvent válido": [
        ("test_m45_end_to_end.py", "test_no_ledger_entry_exists_without_a_valid_applied_payment_event"),
        ("test_revenue_ledger.py", "test_every_payment_with_money_has_exactly_one_capture_entry_and_the_amounts_match"),
        ("test_revenue_ledger.py", "test_the_database_itself_refuses_malformed_or_repeated_entries"),
        (
            "test_revenue_reconciliation.py",
            "test_c3_an_entry_whose_event_is_not_what_it_claims_is_reported_with_its_reasons",
        ),
        ("test_m45_walk.py", "test_a_random_walk_keeps_the_verified_money_coherent_at_every_step"),
    ],
    "un cobro verificado duplicado no produce ingreso doble": [
        ("test_revenue_ledger.py", "test_the_same_capture_delivered_twice_is_one_entry"),
        ("test_revenue_ledger.py", "test_the_same_capture_announced_under_another_event_id_adds_no_entry"),
        ("test_revenue_ledger_concurrency.py", "test_the_same_capture_delivered_twelve_times_at_once_is_one_entry"),
        ("test_m45_end_to_end.py", "test_delivering_every_webhook_again_changes_nothing"),
    ],
    "CONFLICT, UNMATCHED y DUPLICATE_CAPTURE no son ingreso confirmado": [
        ("test_revenue_ledger.py", "test_a_duplicate_capture_is_money_under_review_not_revenue"),
        (
            "test_revenue_ledger.py",
            "test_a_second_capture_event_with_another_amount_is_a_conflict_with_no_entry_and_stays_visible",
        ),
        (
            "test_revenue_ledger.py",
            "test_an_event_that_matches_none_of_our_payments_is_kept_as_pending_evidence_and_is_not_revenue",
        ),
        ("test_revenue_aggregates.py", "test_pending_evidence_is_never_part_of_any_total"),
        ("test_m45_end_to_end.py", "test_conflict_unmatched_and_duplicate_money_is_never_confirmed_revenue"),
    ],
    "los reembolsos no superan el importe capturado": [
        ("test_refunds_concurrency.py", "test_ten_simultaneous_refunds_never_set_aside_more_than_was_captured"),
        ("test_m44_contract_gaps.py", "test_two_refunds_by_the_provider_cannot_together_exceed_what_was_captured"),
        ("test_m45_end_to_end.py", "test_a_refund_never_exceeds_what_was_captured"),
    ],
    "ningún UNKNOWN_OUTCOME se cierra automáticamente": [
        ("test_economic_invariants.py", "test_i5_an_unknown_outcome_is_never_turned_into_a_safe_failure_automatically"),
        (
            "test_reconciliation_actions.py",
            "test_an_unknown_outcome_is_never_closed_repeated_or_released_by_any_number_of_sweeps",
        ),
        (
            "test_m45_chaos.py",
            "test_no_number_of_reconciliation_passes_changes_an_unknown_outcome_or_its_reserved_money",
        ),
        ("test_m45_end_to_end.py", "test_an_unknown_outcome_is_not_closed_by_any_reconciliation"),
        ("test_m45_walk.py", "test_a_random_walk_keeps_the_verified_money_coherent_at_every_step"),
    ],
    "las operaciones externas no se repiten a ciegas": [
        ("test_chaos_scenarios.py", "test_08_a_retry_in_another_worker_cannot_repeat_the_effect"),
        ("test_chaos_scenarios.py", "test_15_an_adapter_without_idempotency_gets_no_key_and_is_never_replayed"),
        ("test_reconciliation_actions.py", "test_the_sweep_has_no_adapter_and_never_calls_execute_or_reconcile"),
        ("test_m44_crash_matrix.py", "test_a_second_worker_cannot_repeat_what_the_dead_one_may_have_sent"),
        ("test_m45_end_to_end.py", "test_an_external_operation_that_may_have_executed_is_not_repeated_blindly"),
    ],
    "una intención idempotente produce como máximo un efecto": [
        ("test_chaos_scenarios.py", "test_01_twenty_identical_simultaneous_requests_have_one_logical_execution"),
        ("test_economic_invariants.py", "test_i3_an_idempotent_request_has_one_logical_execution"),
        ("test_m45_end_to_end.py", "test_repeating_every_intent_with_its_key_produces_no_second_effect"),
    ],
    "ningún GET escribe": [
        ("test_economic_invariants.py", "test_i10_a_read_produces_no_write_on_any_get_route"),
        (
            "test_m44_contract_gaps.py",
            "test_every_read_route_leaves_the_database_exactly_as_it_found_it_even_with_data_of_every_domain",
        ),
        ("test_revenue_aggregates.py", "test_reading_the_aggregates_never_writes"),
        ("test_revenue_api.py", "test_the_http_reads_write_nothing"),
        ("test_m45_end_to_end.py", "test_no_read_route_writes_anything_on_a_database_full_of_data"),
    ],
    "no se mezclan monedas": [
        (
            "test_revenue_aggregates.py",
            "test_only_eur_is_consolidated_and_the_other_currencies_are_declared_not_aggregable",
        ),
        ("test_orders_pagination.py", "test_currencies_are_never_mixed_and_amounts_stay_exact"),
        ("test_m45_end_to_end.py", "test_a_currency_is_never_added_to_another"),
    ],
    "el registro verificado no afirma que una transacción sea REAL": [
        (
            "test_m45_end_to_end.py",
            "test_every_order_in_the_journey_is_marked_simulated_and_the_ledger_does_not_say_otherwise",
        ),
        ("test_revenue_api.py", "test_no_response_carries_margin_profit_cost_taxes_cash_or_fees"),
    ],
    "las rutas paginadas no silencian truncamientos": [
        ("test_orders_pagination.py", "test_there_is_no_way_left_to_list_orders_that_truncates_without_saying_so"),
        ("test_orders_pagination.py", "test_one_more_than_the_limit_says_so_and_the_next_page_has_exactly_that_one"),
        ("test_revenue_aggregates.py", "test_a_last_page_that_is_exactly_full_says_there_is_nothing_more"),
        (
            "test_m45_end_to_end.py",
            "test_the_paginated_routes_say_when_they_truncate_and_walking_them_visits_everything_once",
        ),
    ],
    "la reconciliación no destruye ni reinterpreta resultados desconocidos": [
        ("test_reconciliation_actions.py", "test_an_old_calling_action_becomes_unknown_and_keeps_its_reservation"),
        (
            "test_m45_chaos.py",
            "test_no_number_of_reconciliation_passes_changes_an_unknown_outcome_or_its_reserved_money",
        ),
        ("test_m45_walk.py", "test_a_random_walk_keeps_the_verified_money_coherent_at_every_step"),
    ],
    "los agregados dicen lo que dicen las entradas": [
        ("test_revenue_aggregates.py", "test_the_summary_is_the_sum_of_the_entries_that_explain_it"),
        ("test_revenue_aggregates.py", "test_the_summary_matches_what_the_payments_say_for_every_currency_and_class"),
        ("test_m45_walk.py", "test_a_random_walk_keeps_the_verified_money_coherent_at_every_step"),
    ],
    "Proyectos no puede mostrar ingresos: nada une un proyecto con un pedido": [
        ("test_m45_end_to_end.py", "test_projects_carry_no_money_because_nothing_links_a_project_to_an_order"),
    ],
    # --- Caos ---
    "caída antes de begin_call": [
        (
            "test_m44_crash_matrix.py",
            "test_A_dying_before_the_call_sent_nothing_and_the_sweep_releases_what_was_set_aside",
        ),
        (
            "test_chaos_scenarios.py",
            "test_03_a_worker_that_dies_after_reserving_leaves_a_reservation_the_sweep_releases",
        ),
    ],
    "caída después de begin_call": [
        ("test_m44_crash_matrix.py", "test_C_D_E_when_the_provider_executed_the_database_never_says_half_done"),
        (
            "test_m45_chaos.py",
            "test_a_process_that_dies_after_crossing_the_frontier_is_unknown_and_no_scheduled_sweep_releases_it",
        ),
        (
            "test_chaos_scenarios.py",
            "test_04_a_worker_that_dies_after_the_boundary_but_before_any_effect_is_still_unknown",
        ),
    ],
    "respuesta tardía": [
        (
            "test_chaos_scenarios.py",
            "test_07_a_late_response_settles_the_operation_once_and_a_second_delivery_changes_nothing",
        ),
        ("test_reconciliation_actions.py", "test_a_late_response_closes_what_the_sweep_marked_unknown"),
    ],
    "lease vencido": [
        ("unit/test_job_worker.py", "test_each_cycle_reaps_dead_leases_before_claiming"),
        (
            "test_m45_chaos.py",
            "test_a_worker_that_dies_holding_the_reconciliation_tick_is_replaced_and_the_money_counts_once",
        ),
    ],
    "dos workers sobre la misma operación": [
        ("test_chaos_scenarios.py", "test_08_a_retry_in_another_worker_cannot_repeat_the_effect"),
        (
            "test_m44_concurrency.py",
            "test_two_workers_resuming_the_same_unknown_outcome_move_the_domain_and_the_ledger_once",
        ),
        ("test_reconciliation_actions.py", "test_several_reconcilers_at_once_move_every_action_exactly_once"),
        ("test_m45_chaos.py", "test_two_workers_taking_the_same_tick_at_once_apply_the_stored_event_once"),
    ],
    "webhook duplicado": [
        ("test_payment_events_concurrency.py", "test_the_same_event_delivered_twelve_times_at_once_is_applied_once"),
        ("test_revenue_ledger_concurrency.py", "test_the_same_capture_delivered_twelve_times_at_once_is_one_entry"),
    ],
    "webhook fuera de orden": [
        ("test_payment_events.py", "test_a_late_capture_after_a_failure_is_recorded_and_pays_the_order"),
        ("test_m45_chaos.py", "test_events_in_any_order_leave_the_same_verified_revenue_and_nothing_invented"),
    ],
    "evento con el mismo ID y payload distinto": [
        (
            "test_provider_event_conflict.py",
            "test_the_same_id_made_at_another_instant_is_a_conflict_that_keeps_the_original_and_touches_nothing",
        ),
        (
            "test_provider_event_conflict.py",
            "test_a_conflicting_delivery_leaves_an_event_in_any_settled_state_as_it_was",
        ),
        ("test_m45_end_to_end.py", "test_conflict_unmatched_and_duplicate_money_is_never_confirmed_revenue"),
    ],
    "reembolso concurrente": [
        ("test_refunds_concurrency.py", "test_ten_simultaneous_refunds_never_set_aside_more_than_was_captured"),
        ("test_refunds_concurrency.py", "test_two_refunds_that_do_not_fit_together_leave_exactly_one"),
        (
            "test_revenue_ledger_concurrency.py",
            "test_a_mixed_storm_of_captures_duplicates_and_refunds_leaves_the_ledger_matching_the_payments",
        ),
    ],
    "compra y cancelación concurrentes": [
        ("test_fulfilment_concurrency.py", "test_buying_and_cancelling_at_once_never_both_win"),
        (
            "test_fulfilment_concurrency.py",
            "test_a_cancellation_while_the_purchase_is_in_flight_is_refused_and_keeps_the_units",
        ),
    ],
    "el reconciliador a la vez que una respuesta tardía": [
        (
            "test_m44_concurrency.py",
            "test_reconciliation_the_late_response_and_a_person_cannot_all_close_the_same_unknown_outcome",
        ),
        (
            "test_reconciliation_events.py",
            "test_reconcilers_redelivery_and_a_retry_at_once_move_the_money_exactly_once",
        ),
    ],
    "tormenta concurrente con el registro de ingresos mirando": [
        ("test_m45_chaos.py", "test_a_concurrent_storm_leaves_the_ledger_matching_the_payments_and_nothing_rewritten"),
        (
            "test_m44_concurrency.py",
            "test_a_storm_of_concurrent_random_operations_leaves_a_coherent_state_and_nothing_half_done",
        ),
    ],
}


def _tests_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def _locate(name: str) -> Path:
    return UNIT / name.removeprefix("unit/") if name.startswith("unit/") else HERE / name


def test_every_sentence_of_the_brief_has_an_owner_and_every_owner_exists():
    missing: list[str] = []
    for sentence, owners in COVERAGE.items():
        assert owners, f"«{sentence}» has no test"
        for file, name in owners:
            path = _locate(file)
            if not path.exists():
                missing.append(f"«{sentence}»: {file} does not exist")
            elif name not in _tests_in(path):
                missing.append(f"«{sentence}»: {file}::{name} is gone (deleted or renamed)")
    assert missing == [], "\n".join(missing)


#: Las frases que nacen en este commit: no tienen dueño anterior, y se declaran para que ninguna otra pueda esconderse
#: aquí. («Proyectos no muestra ingresos» es una consecuencia de la decisión D1 del propietario, que se tomó en el
#: Commit 11 y no tenía prueba de backend: el modelo no enlaza proyectos con pedidos.)
BORN_IN_THIS_COMMIT = {"Proyectos no puede mostrar ingresos: nada une un proyecto con un pedido"}


def test_every_invariant_that_is_not_new_has_an_owner_older_than_this_commit():
    """Si todo lo que sostiene una frase se añadió hoy, el mapa no demuestra que no se duplicó nada, y es probable que
    falte una prueba anterior que sí existe."""
    for sentence, owners in COVERAGE.items():
        previous = [owner for owner in owners if not owner[0].startswith("test_m45_")]
        if sentence in BORN_IN_THIS_COMMIT:
            assert not previous
        else:
            assert previous, f"«{sentence}» is held up only by tests of this commit"
