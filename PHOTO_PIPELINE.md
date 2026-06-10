# 照片品牌识别流水线

这个工具会扫描照片、生成 OpenAI Batch 请求、解析识别结果，并把高置信度且不歧义的品牌写入 Appwrite。原图不会被复制到仓库，只会在 `photo-runs/` 里生成压缩预览图、JSONL、CSV 报告和写入日志。

## 准备

```powershell
cd E:\GitHub\foodtalks-checkin
uv sync
$env:OPENAI_API_KEY="你的 OpenAI API Key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:APPWRITE_API_KEY="你的 Appwrite API Key"
$env:APPWRITE_USER_ID="要标记打卡的 Appwrite 用户 ID"
```

如果使用 OpenAI-compatible 内网服务，把 `OPENAI_BASE_URL` 改成对应地址，例如 `http://192.168.124.160:8317/v1`。部分兼容服务不支持官方 Batch API；如果 `submit-batch` 返回 404，就用 `run-sync` 同步模式。

Appwrite API Key 需要能读写 TablesDB 的 `checkins` 表。密钥只放环境变量或本机 `.env`，不要提交。

## 小批量试跑

共用电脑建议把 `run-dir` 放到 C 盘照片目录旁边，例如 `C:\Users\addAdministrators\Pictures\photos\photo-runs\sample`，不要占 E 盘空间。

```powershell
uv run python -m tools.brand_photo_checkin prepare "C:\Users\addAdministrators\Pictures\photos\相册" --run-dir "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample" --limit 30
uv run python -m tools.brand_photo_checkin submit-batch "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample"
uv run python -m tools.brand_photo_checkin fetch-batch <batch_id> "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample"
uv run python -m tools.brand_photo_checkin ingest "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample"
uv run python -m tools.brand_photo_checkin write-appwrite "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample"
```

内网兼容服务如果不支持 Batch API，把上面的 `submit-batch` 和 `fetch-batch` 两步换成：

```powershell
uv run python -m tools.brand_photo_checkin run-sync "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample"
```

最后一步默认是 dry-run，只会生成 `rollback.json` 并提示将写入多少品牌。确认 `auto_write.csv` 和 `needs_review.csv` 后，再执行：

```powershell
uv run python -m tools.brand_photo_checkin write-appwrite "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample" --execute
```

跑完后清理照片预览、请求文件和模型原始输出：

```powershell
uv run python -m tools.brand_photo_checkin cleanup-run "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample"
```

如果连 CSV/JSON 报告也不想保留：

```powershell
uv run python -m tools.brand_photo_checkin cleanup-run "C:\Users\addAdministrators\Pictures\photos\photo-runs\sample" --no-keep-reports
```

## 全量流程

全量跑时不要设置 `--limit`，并建议用新的 `run-dir`：

```powershell
uv run python -m tools.brand_photo_checkin prepare "C:\Users\addAdministrators\Pictures\photos\相册" --run-dir "C:\Users\addAdministrators\Pictures\photos\photo-runs\full"
uv run python -m tools.brand_photo_checkin submit-batch "C:\Users\addAdministrators\Pictures\photos\photo-runs\full"
uv run python -m tools.brand_photo_checkin fetch-batch <batch_id> "C:\Users\addAdministrators\Pictures\photos\photo-runs\full"
uv run python -m tools.brand_photo_checkin ingest "C:\Users\addAdministrators\Pictures\photos\photo-runs\full" --threshold 0.82
uv run python -m tools.brand_photo_checkin write-appwrite "C:\Users\addAdministrators\Pictures\photos\photo-runs\full"
```

不支持 Batch API 时，全量流程也同样把 `submit-batch` 和 `fetch-batch` 换成 `run-sync`。

## 输出文件

- `photos.jsonl`：照片路径、哈希、预览图路径，支持断点和审计。
- `batch_requests.jsonl`：可上传到 OpenAI Batch API 的请求文件。
- `batch_output.jsonl`：OpenAI Batch 返回结果。
- `auto_write.csv` / `auto_write.json`：可自动写入 Appwrite 的品牌。
- `needs_review.csv`：公司名或品牌名对应多个 `brand_id`、或置信度不足的结果。
- `unmatched.csv`：模型读到了文字，但本地品牌表没有匹配到。
- `appwrite_write_log.jsonl`：真实写入 Appwrite 后的返回日志。
- `rollback.json`：本次计划写入的 brand_id 清单，便于人工回滚。
