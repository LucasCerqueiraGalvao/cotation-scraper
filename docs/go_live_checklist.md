# Go-live Checklist

Last update: 2026-03-31

## T-24h

- [ ] Freeze code changes for production branch
- [ ] Confirm target image tag for release
- [ ] Confirm rollback tag (last stable)
- [ ] Validate required secrets in `prod` Key Vault
- [ ] Confirm alert action group and recipients

## T-2h

- [ ] Validate `prod` job configuration
- [ ] Run one manual smoke in `prod` (no full benchmark required)
- [ ] Confirm SharePoint upload permissions and destination folder

## Go-live

- [ ] Deploy release tag to `prod`
- [ ] Enable/confirm scheduled trigger
- [ ] Record deployment timestamp, tag and operator

## Post Go-live (same day)

- [ ] Validate first scheduled execution started at expected time
- [ ] Validate files generated:
  - `comparacao_carriers_cliente.xlsx`
  - `comparacao_carriers_cliente_special.xlsx`
  - `comparacao_carriers_cliente_granito.xlsx`
- [ ] Validate no critical alerts fired

## Rollback Trigger

- [ ] Two consecutive failed production runs
- [ ] SharePoint upload failure blocking delivery for more than one cycle
- [ ] Critical regression with no same-day fix
