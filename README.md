# Контракти даних у хмарних ETL-конвеєрах AWS

Експериментальна частина статті «Контракти даних як механізм забезпечення цілісності
даних у хмарних ETL-конвеєрах AWS в умовах цифрової трансформації».

Експеримент порівнює чотири механізми контролю на 12 сценаріях змін вхідних даних:

| Механізм | Де працює | Файл |
|---|---|---|
| Без контракту | Glue job (PySpark, `inferSchema`) | `glue/orders_etl_dq.py` |
| Glue Schema Registry | реєстрація схеми виробником, режим BACKWARD / FULL | `src/schema_registry_check.py` |
| Glue Data Quality | правила DQDL у Glue job | `glue/ruleset.dqdl` |
| Контракт даних ODCS | Lambda на вході в озеро даних | `contracts/orders.odcs.yaml`, `lambda/` |

Правила Glue Data Quality **генеруються з контракту** (`src/contract_to_dqdl.py`), тому контракт
є єдиним джерелом правил для всіх точок перевірки.

## Результати

Glue 4.0 (Spark 3.3), регіон eu-central-1, 200 записів у кожному файлі.

| Механізм | Виявлено несумісних змін | Хибні тривоги на сумісних змінах |
|---|---|---|
| Без контракту (ETL) | 0 з 10 | 0 |
| Glue Schema Registry, BACKWARD | 3 з 10 | 1 (нове необов'язкове поле) |
| Glue Schema Registry, FULL | 5 з 10 | 1 (нове необов'язкове поле) |
| Glue Data Quality (правила з контракту) | 9 з 10 (пропущено зміну регістру імені поля) | 0 |
| Контракт даних ODCS | 10 з 10 | 0 |

Повні таблиці: [`results/matrix_backward.md`](results/matrix_backward.md),
[`results/matrix_full.md`](results/matrix_full.md); деталі (помилки, виведені схеми, час) —
`results/raw_results_backward.json`, `results/raw_results_full.json`.

## Архітектура

```
файл CSV ─► s3://<bucket>/landing/ ──(S3 event)──► Lambda (контракт ODCS)
                     │                                ├─► validated/   (дані відповідають контракту)
                     │                                ├─► quarantine/  (порушення) ─► SNS-сповіщення
                     │                                └─► results/contract/*.json
                     └──► Glue job (PySpark) ──► lake/orders/ (Parquet)
                                   └── Glue Data Quality ──► results/glue/*.json
Glue Schema Registry ◄── версії схеми виробника (src/schema_registry_check.py)
```

## Що потрібно

* AWS-акаунт і налаштований AWS CLI (`aws configure`)
* Terraform ≥ 1.5
* Python 3.10–3.11 і `pip install -r requirements.txt`
  (PySpark 3.3 не працює на Python ≥ 3.12; PySpark і Java 11/17 потрібні лише для локального прогону)

Вартість одного повного прогону: менше 1 $ (13 коротких запусків Glue по 2 DPU,
решта в межах Free Tier). **Після експерименту обов'язково виконайте `terraform destroy`.**

## Запуск

```bash
# 0. Середовище
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1. Локальний прогін без AWS (перевірка контракту; Spark — якщо доступний)
python src/local_experiment.py

# 2. Пакет Lambda (Linux/macOS/Git Bash)
bash scripts/build_lambda.sh

# 3. Інфраструктура
cd terraform
terraform init
terraform apply                    # опційно: -var="alert_email=you@example.com"
cd ..
# зачекайте 2–3 хв: сповіщення S3 -> Lambda починають працювати не одразу

# 4. Експеримент (~15 хв)
python src/run_experiment.py --glue-batch 2
cp results/matrix.md results/matrix_backward.md
cp results/raw_results.json results/raw_results_backward.json

# 4a. Опційно: реєстр схем у режимі FULL (без Glue job, ~2 хв)
python src/run_experiment.py --skip-glue --compatibility FULL
cp results/matrix.md results/matrix_full.md
cp results/raw_results.json results/raw_results_full.json

# 5. Прибирання
cd terraform && terraform destroy
```

Пакет Lambda у PowerShell без bash:

```powershell
pip install --target build\lambda --platform manylinux2014_x86_64 --implementation cp `
  --python-version 3.12 --only-binary=:all: PyYAML
Copy-Item lambda\handler.py, lambda\contract_validator.py build\lambda\
```

Якщо вказали `alert_email`, підтвердіть підписку в листі від AWS до запуску експерименту.

## Структура

```
contracts/orders.odcs.yaml     контракт даних (ODCS v3)
src/scenarios.py               12 сценаріїв змін + еталон
src/generate_data.py           генерація CSV і JSON-схем виробника
src/contract_to_dqdl.py        контракт -> правила Glue Data Quality
src/schema_registry_check.py   перевірка в Glue Schema Registry
src/run_experiment.py          повний експеримент в AWS
src/local_experiment.py        локальний прогін (без AWS)
src/matrix.py                  побудова підсумкової таблиці
lambda/                        валідатор контракту (Lambda)
glue/                          Glue job і правила DQDL
terraform/                     уся інфраструктура
results/                       результати експерименту
```

## Можливі проблеми

* `AccessDenied` під час `terraform apply` — у користувача CLI немає прав на IAM/Glue;
  для навчального акаунта найпростіше використовувати користувача з `AdministratorAccess`.
* `archive has not been created as it would be empty` — не зібрано пакет Lambda (крок 2).
* `TimeoutError: не дочекалися .../results/contract/...` одразу після `terraform apply` —
  сповіщення S3 ще не активувались; зачекайте кілька хвилин і запустіть ще раз.
* Glue job `FAILED` з `ResourceNumberLimitExceeded` — запустіть з `--glue-batch 1`.
* `UnicodeDecodeError` у pip на Windows — `$env:PYTHONUTF8 = "1"` або оновіть pip.
