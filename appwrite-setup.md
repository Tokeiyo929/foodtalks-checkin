# Appwrite 设置

在 Appwrite Console 中完成以下配置后，把对应 ID 填入 `appwrite-config.js`。

## Auth

1. 在 Auth 的 OAuth2 providers 中启用 GitHub。
2. 在 GitHub OAuth App 中添加回调地址：
   `https://cloud.appwrite.io/v1/account/sessions/oauth2/callback/github/<PROJECT_ID>`
3. 如果使用自托管 Appwrite，把回调地址里的 `https://cloud.appwrite.io/v1` 换成你的 Appwrite endpoint。
4. 在项目平台设置中添加站点域名，例如本地预览的 `http://127.0.0.1:8766` 和 GitHub Pages 域名。

## TablesDB

1. 新建 Database，复制 Database ID。
2. 新建 Table，Table ID 建议使用 `checkins`。
3. 添加 Columns：
   - `user_id`：String，size 64，required
   - `brand_id`：Integer，required
   - `checked_at`：String，size 40，required
4. 添加 Indexes：
   - `user_id_idx`：key，column `user_id`
   - `brand_id_idx`：key，column `brand_id`
   - `user_brand_idx`：key，columns `user_id`, `brand_id`
5. Table permissions：
   - Create：Users
   - Read / Update / Delete 不给全表权限，记录由前端创建时写入当前用户的 row permissions。
