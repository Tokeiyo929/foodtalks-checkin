# 食品品牌吃过打卡地图

一个可以部署到 GitHub Pages 的静态打卡网站。品牌数据来自 FoodTalks 文章整理结果，打卡记录支持 Supabase 云端存储。

## 本地预览

```powershell
cd E:\GitHub\foodtalks-checkin
python -m http.server 8766 --bind 127.0.0.1
```

打开 `http://127.0.0.1:8766/`。

## Supabase 设置

1. 新建 Supabase 项目。
2. 在 Supabase SQL Editor 运行 `supabase-schema.sql`。
3. 在 Authentication settings 开启 Anonymous Sign-ins。
4. 复制 Project URL 和 anon public key，填入 `supabase-config.js`：

```js
window.SUPABASE_CONFIG = {
  url: "https://你的项目.supabase.co",
  anonKey: "你的 anon public key",
};
```

没有填写 Supabase 配置时，网站会退回浏览器本地存储模式。

## 部署到 GitHub Pages

把这个目录提交到 GitHub 仓库，然后在仓库 Settings -> Pages 里选择部署分支即可。
