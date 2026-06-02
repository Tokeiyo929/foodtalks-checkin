# 食品品牌吃过打卡地图

一个可以部署到 GitHub Pages 的静态打卡网站。品牌数据来自 FoodTalks 文章整理结果，打卡记录支持 Appwrite 云端存储。

## 本地预览

```powershell
cd E:\GitHub\foodtalks-checkin
python -m http.server 8766 --bind 127.0.0.1
```

打开 `http://127.0.0.1:8766/`。

## Appwrite 设置

1. 新建 Appwrite 项目。
2. 在 Auth 中启用 GitHub OAuth 登录。
3. 按 `appwrite-setup.md` 创建 TablesDB Database、`checkins` Table、Columns、Indexes 和权限。
4. 复制 Endpoint、Project ID、Database ID 和 Table ID，填入 `appwrite-config.js`：

```js
window.APPWRITE_CONFIG = {
  endpoint: "https://cloud.appwrite.io/v1",
  projectId: "你的 project id",
  databaseId: "你的 database id",
  tableId: "checkins",
};
```

没有填写 Appwrite 配置时，网站会退回浏览器本地存储模式。

## 部署到 GitHub Pages

把这个目录提交到 GitHub 仓库，然后在仓库 Settings -> Pages 里选择部署分支即可。
