# Eval Execution Report

- Started: `2026-05-25T16:06:42.634518+00:00`
- Completed: `2026-05-25T16:06:42.749059+00:00`
- Duration: `0.115s`
- Scenarios: `4`
- Passed suites: `8`
- Failed suites: `0`

## Suites

### contracts_registry
- Status: `passed`
- Check: TaskContract creation and validation
- Check: Pulsar registration for Vega and Rigel
- Check: Skill lookup for QA and engineering paths

### vega_pipeline
- Status: `passed`
- Check: Finance Vega flow
- Check: Health Vega flow
- Check: Hospitality Vega flow
- Check: Retail Vega flow
- Artifacts: `{"finance_ach_payroll": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "0114d54d-3f22-4f93-a447-5b57a4cbdaeb"}, "health_fhir_intake": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "4b9f812d-b992-4ae4-b637-104261111116"}, "hospitality_booking": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "7b558f21-6ebc-471b-a05b-2e21b195394a"}, "retail_gtin_catalog": {"bugs": 0, "feedback_stream": "galaxz.feedback.vega", "run_id": "68ab02ce-82f6-412f-abfa-3146fbbdbc01"}}`

### rigel_skills
- Status: `passed`
- Check: Code generation with execution calibration
- Check: Test writing
- Check: PR review
- Check: Debug triage
- Check: Refactor
- Check: Scaffold
- Artifacts: `{"codegen_confidence": 0.988, "feedback_events": 6}`

### andromeda_routing
- Status: `passed`
- Check: Vega routing
- Check: Rigel routing
- Check: No-match routing
- Check: Task log persistence
- Artifacts: `{"rigel_task_id": "284d8910-9a78-45ef-814e-3a7349aaa3c3", "vega_task_id": "17d5d4cf-8357-4728-a771-c1b4aea75382"}`

### cli_surface
- Status: `passed`
- Check: CLI Vega command
- Check: CLI route command

### api_surface
- Status: `passed`
- Check: FastAPI health endpoint
- Check: FastAPI bearer auth for write endpoints
- Check: FastAPI task routing endpoint
- Check: FastAPI status endpoint
- Check: FastAPI review queue approve/reject endpoints
- Check: FastAPI fine-tune candidate approve/reject endpoints

### orion_pipeline
- Status: `passed`
- Check: Direct Orion ingest for accepted and rejected feedback
- Check: Dataset curation cycle
- Check: Heuristic cycle with routing, drift, and fine-tune signals
- Artifacts: `{"heuristic_streams": ["aether:orion.drift_alert", "aether:orion.fine_tune_ready", "aether:routing.heuristic_update"], "ingest_dataset_root": "/var/folders/gy/0hlyycgx1k17_04kb4836njr0000gn/T/galaxz-eval-orion-t_gvlwe8/datasets"}`

### feedback_handshake
- Status: `passed`
- Check: Andromeda to Vega execution
- Check: Andromeda to Rigel execution
- Check: Agent feedback payload compatibility with Orion ingest
- Artifacts: `{"eligible_ingests": 2, "feedback_events": 2}`

## Dataset Sources

- finance: Nacha ACH (https://achdevguide.nacha.org/ach-file-overview)
- health: HL7 FHIR Patient and Observation (https://www.hl7.org/fhir/patient.html)
- hospitality: OpenTravel Messaging (https://opentravel.org/opentravel-messaging-business-functionality/)
- retail: GS1 GTIN / Barcode Standards (https://www.gs1.org/standards/barcodes)
