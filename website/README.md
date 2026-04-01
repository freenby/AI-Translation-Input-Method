# AI翻译输入法 - 宣传网站

## 文件结构

```
website/
├── index.html          # 主页面（单页应用）
├── download/           # 存放安装包
│   └── AI翻译输入法_Setup.exe
└── README.md           # 本文件
```

## 部署方法

### 方法一：静态托管（推荐）

1. 将 `website` 文件夹上传到任意静态托管服务：
   - GitHub Pages（免费）
   - Vercel（免费）
   - Netlify（免费）
   - 阿里云 OSS
   - 腾讯云 COS

2. 将安装包 `AI翻译输入法_Setup.exe` 放入 `download/` 文件夹

### 方法二：本地预览

直接双击 `index.html` 在浏览器中打开即可预览。

## 修改内容

网站是纯静态 HTML，直接编辑 `index.html` 即可：

- **修改下载链接**: 搜索 `download/AI翻译输入法_Setup.exe`
- **修改版本号**: 搜索 `v1.0.0`
- **修改联系方式**: 在 footer 区域添加
- **修改颜色主题**: 修改 `:root` 中的 CSS 变量

## 特点

- 单文件，无需构建
- 响应式设计，支持手机访问
- 深色主题，现代风格
- FAQ 可点击展开
- 平滑滚动导航
