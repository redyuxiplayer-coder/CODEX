# 登录页手机版/电脑版切换 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在手机版与电脑版两个登录页上互加“手机版 / 电脑版”手动切换入口，不改登录逻辑。

**Architecture:** 电脑版登录页是 Vue 单页应用（`web/src/views/Login.vue`，构建后由 `/app` 提供）；手机版登录页是服务端模板（`app/templates/mobile/login.html`）。两个页面各自加一段纯 HTML 跳转入口，共用一段简单 CSS 观感，互相用链接跳转到 `/mobile/login` 与 `/app`。

**Tech Stack:** Python FastAPI + Jinja2、Vue 3 + Vite、nginx/systemd（部署目标为新服务器 `47.109.138.202`）。

## Global Constraints

- 只更新新服务器，旧腾讯云服务器不再操作。
- 不改登录接口、不改登录后角色跳转逻辑、不做设备自动识别、不记住上次选择。
- 界面文案固定为“手机版”和“电脑版”。
- 修改 `app.css` 后必须同步提升模板中静态文件版本号（本次改为 `?v=20260907-1`）。
- 每个任务结束都要跑测试并提交 Git（前端构建产物不提交，只提交源码与测试）。
- 设计文档：`docs/superpowers/specs/2026-09-07-login-view-switcher-design.md`

---

### Task 1: 手机版登录页增加“电脑版”入口

**Files:**
- Modify: `tests/test_pages.py`（在 `test_pages_render` 附近新增测试）
- Modify: `app/templates/mobile/login.html`
- Modify: `app/static/app.css`

**Interfaces:**
- Consumes: 现有 `GET /mobile/login` 路由，渲染 `mobile/login.html`。
- Produces: 手机版登录页 HTML 中出现 `href="/app"` 的“电脑版”入口。

- [ ] **Step 1: 写失败测试**

在 `tests/test_pages.py` 顶部已有 `BASE_DIR` 与 `TestClient` 导入。把下面测试插在 `test_pages_render` 函数之后：

```python
def test_mobile_login_page_offers_desktop_entry():
    client = TestClient(create_app())
    html = client.get("/mobile/login").text
    assert "手机版" in html
    assert "电脑版" in html
    assert 'href="/app"' in html
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pages.py::test_mobile_login_page_offers_desktop_entry -q`

Expected: FAIL，`AssertionError: assert 'href="/app"' in html`。

- [ ] **Step 3: 修改手机版登录模板**

将 `app/templates/mobile/login.html` 全文替换为：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>员工登录</title>
  <link rel="stylesheet" href="/static/app.css?v=20260907-1">
</head>
<body class="mobile">
  <main class="phone-card">
    <h1>员工登录</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <form method="post" action="/login" class="grid-form">
      <input name="username" placeholder="账号" required>
      <input name="password" type="password" placeholder="密码" required>
      <button>登录</button>
    </form>
    <div class="version-switch" role="group" aria-label="版本选择">
      <span class="version-switch-item is-active">手机版</span>
      <a class="version-switch-item" href="/app">电脑版</a>
    </div>
  </main>
</body>
</html>
```

注意：`app.css` 版本号从 `?v=20260804-7` 改为 `?v=20260907-1`。

- [ ] **Step 4: 追加手机版页面样式**

在 `app/static/app.css` 末尾追加：

```css
.version-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.version-switch-item {
  display: block;
  text-align: center;
  padding: 8px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  color: #2563eb;
  text-decoration: none;
  background: #ffffff;
}

.version-switch-item.is-active {
  background: #f3f4f6;
  color: #6b7280;
  cursor: default;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_pages.py::test_mobile_login_page_offers_desktop_entry tests/test_pages.py::test_pages_render -q`

Expected: PASS（2 passed）。

- [ ] **Step 6: 提交**

```bash
git add tests/test_pages.py app/templates/mobile/login.html app/static/app.css
git commit -m "feat: add desktop version entry to mobile login page"
```

---

### Task 2: 电脑版登录页增加“手机版”入口

**Files:**
- Modify: `tests/test_pages.py`
- Modify: `web/src/views/Login.vue`
- Build: `web/dist`（构建产物，不提交）

**Interfaces:**
- Consumes: Vue 登录页源码 `Login.vue`，已有 `login()` 与 `/app` 路由。
- Produces: 电脑版登录页出现 `href="/mobile/login"` 的“手机版”入口；Vue 构建成功。

- [ ] **Step 1: 写失败测试**

把下面测试插在 Task 1 新增测试之后：

```python
def test_admin_login_source_offers_mobile_entry():
    source = (BASE_DIR / "web" / "src" / "views" / "Login.vue").read_text(encoding="utf-8")
    assert "手机版" in source
    assert 'href="/mobile/login"' in source
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pages.py::test_admin_login_source_offers_mobile_entry -q`

Expected: FAIL，`AssertionError: assert 'href="/mobile/login"' in source`。

- [ ] **Step 3: 修改 Vue 登录页模板部分**

在 `web/src/views/Login.vue` 中，把 `<template>` 里 `</el-form>` 之后、`</el-card>` 之前插入：

```html
      <div class="version-switch" role="group" aria-label="版本选择">
        <a class="version-switch-item" href="/mobile/login">手机版</a>
        <span class="version-switch-item is-active">电脑版</span>
      </div>
```

修改后 `<template>` 对应区域为：

```html
      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="username" placeholder="账号" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" type="password" placeholder="密码" size="large" show-password @keyup.enter="submit" />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom:12px" />
        <el-button type="primary" size="large" style="width:100%" :loading="loading" @click="submit">登录</el-button>
      </el-form>
      <div class="version-switch" role="group" aria-label="版本选择">
        <a class="version-switch-item" href="/mobile/login">手机版</a>
        <span class="version-switch-item is-active">电脑版</span>
      </div>
```

- [ ] **Step 4: 追加 Vue 页面样式**

在 `web/src/views/Login.vue` 的 `<style scoped>` 末尾追加：

```css
.version-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
}

.version-switch-item {
  display: block;
  text-align: center;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  color: #2563eb;
  text-decoration: none;
  background: #ffffff;
}

.version-switch-item.is-active {
  background: #f3f4f6;
  color: #6b7280;
  cursor: default;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_pages.py::test_admin_login_source_offers_mobile_entry -q`

Expected: PASS。

- [ ] **Step 6: 构建前端并确认产物**

Run（在仓库根目录 `E:\CODEX\1-项目\仓库系统管理\订单报表系统`）：

```powershell
cd web
npm run build
cd ..
```

Expected: 构建成功，无报错。

然后确认构建产物包含手机版入口字符串：

Run: `rg -l "mobile/login" web/dist/assets`

Expected: 至少输出一个 `.js` 文件路径。

- [ ] **Step 7: 提交源码与测试**

```bash
git add tests/test_pages.py web/src/views/Login.vue
git commit -m "feat: add mobile version entry to desktop login page"
```

`web/dist` 不提交。

---

### Task 3: 部署到新服务器并验证

**Files:**
- Deploy: `web/dist/`、`app/templates/mobile/login.html`、`app/static/app.css`
- Target: 新服务器 `47.109.138.202:/home/ubuntu/zy-shipping/`

**Interfaces:**
- Consumes: Task 1 模板/样式、Task 2 构建产物。
- Produces: 新服务器上两个登录页都能看到版本切换入口。

- [ ] **Step 1: 同步文件到新服务器**

在仓库根目录执行：

```powershell
rsync -a web/dist/ root@47.109.138.202:/home/ubuntu/zy-shipping/web/dist/
scp app/templates/mobile/login.html root@47.109.138.202:/home/ubuntu/zy-shipping/app/templates/mobile/login.html
scp app/static/app.css root@47.109.138.202:/home/ubuntu/zy-shipping/app/static/app.css
```

（如果本机没有 rsync 到服务器的配置，可先用 `scp -r web/dist root@47.109.138.202:/tmp/newdist/` 再在服务器上移动到目标目录。）

- [ ] **Step 2: 重启服务并验证手机版页面**

Run:

```powershell
ssh root@47.109.138.202 "systemctl restart zy-shipping; sleep 3; curl -s http://127.0.0.1/mobile/login | grep -o 'version-switch\|href=\"/app\"\|电脑版'"
```

Expected: 输出包含 `version-switch`、`href="/app"`、`电脑版`。

- [ ] **Step 3: 验证电脑版页面构建产物**

Run:

```powershell
ssh root@47.109.138.202 "curl -s http://127.0.0.1/app/ | grep -o 'index-[A-Za-z0-9_-]*\.js'"
```

取返回的 JS 文件名 `<name>`，然后运行：

```powershell
ssh root@47.109.138.202 "curl -s http://127.0.0.1/app/assets/<name> | grep -o 'mobile/login'"
```

Expected: 输出 `mobile/login`。

- [ ] **Step 4: 交用户实测**

让用户在浏览器分别打开 `http://47.109.138.202/app` 与 `http://47.109.138.202/mobile/login`，确认登录页上有“手机版 / 电脑版”切换且跳转正常。

---

## Self-Review 记录

- 设计文档每条需求均有对应任务：手机版入口（Task 1）、电脑版入口（Task 2）、部署验证（Task 3）。
- 无 TBD/TODO 占位；所有代码步骤均给出完整内容。
- 链接地址一致：手机版入口一律 `href="/mobile/login"`，电脑版入口一律 `href="/app"`；文案固定“手机版 / 电脑版”。
