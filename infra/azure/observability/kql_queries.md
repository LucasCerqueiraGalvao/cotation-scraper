# KQL Queries - Cotation Scrapers

Use these queries in Log Analytics (workspace linked to Container Apps Environment).

## Last 50 Pipeline Logs

```kql
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(7d)
| where Log_s has "Pipeline"
| sort by TimeGenerated desc
| take 50
```

## Failures by Stage (7d)

```kql
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(7d)
| where Log_s has "Falha na etapa" or Log_s has "Falha na etapa paralela"
| extend stage =
    case(
        Log_s has "hapag", "hapag",
        Log_s has "maersk", "maersk",
        Log_s has "comparison", "comparison",
        Log_s has "upload", "upload",
        "other"
    )
| summarize failures=count() by stage
| order by failures desc
```

## Success Rate (30d)

```kql
let runs =
    ContainerAppConsoleLogs_CL
    | where TimeGenerated > ago(30d)
    | where Log_s has "Pipeline concluido com sucesso." or Log_s has "Pipeline encerrado com erro."
    | extend run_status = iff(Log_s has "sucesso", "success", "error")
    | summarize total=count(), success=countif(run_status == "success"), error=countif(run_status == "error");
runs
| extend success_rate = iff(total == 0, 0.0, todouble(success) / todouble(total) * 100.0)
```

## Approximate Runtime per Run

```kql
let start =
    ContainerAppConsoleLogs_CL
    | where TimeGenerated > ago(7d)
    | where Log_s has "Pipeline iniciado."
    | project run_start=TimeGenerated;
let finish =
    ContainerAppConsoleLogs_CL
    | where TimeGenerated > ago(7d)
    | where Log_s has "Pipeline concluido com sucesso." or Log_s has "Pipeline encerrado com erro."
    | project run_end=TimeGenerated, status=iff(Log_s has "sucesso", "success", "error");
start
| join kind=inner finish on $left.run_start <= $right.run_end
| summarize run_end=min(run_end), status=arg_min(run_end, status) by run_start
| extend duration_min = datetime_diff('minute', run_end, run_start)
| order by run_start desc
```

## SharePoint Upload Events

```kql
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(7d)
| where Log_s has "[sharepoint] upload concluido com sucesso"
| project TimeGenerated, Log_s
| sort by TimeGenerated desc
```

