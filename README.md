# CSU Auto Login

适用于中南大学校园网的 Windows 自动登录工具。程序只会在连接配置文件中 "allowed_ssids" 规定的 WiFi 后进行进行自动登录，默认网络是 "CSU-Student" 和 "CSU-WIFI" 。运行期失败默认只写日志、不弹窗。

## 配置

首次运行前先编辑 `config.json`。

必填项：

- `username`：校园卡账号
- `password`：校园卡密码

常用项：

- `isp_suffix`：运营商后缀，默认 `@cmccn`
- 可选后缀见 `isp_suffix_options`
- `allowed_ssids`：允许自动登录的 Wi-Fi 名称列表
- `hide_console`：是否隐藏控制台窗口，默认 `true`

默认提供的运营商后缀：

- `@cmccn`：移动
- `@unicomn`：联通
- `@telecomn`：电信

## 构建

本项目使用 `uv` 构建。

在项目目录运行：

```bat
build.bat
```

`build.bat` 会自动把 `requests` 和 `pyinstaller` 一起放进临时构建环境。

构建完成后，成品位于：

```text
dist\CSUAutoLogin.exe
dist\config.json
```

分发时把这两个文件一起发出去。

## 开机自启

先完成构建，再运行：

```bat
enable_startup.bat
```

脚本会在当前用户的启动目录创建 `CSUAutoLogin.exe` 的快捷方式。以后登录 Windows 时会自动启动。

## 关闭程序

程序默认隐藏控制台并在后台运行。

如果要关闭：

1. 打开任务管理器
2. 在“进程”或“详细信息”里找到 `CSUAutoLogin.exe`
3. 结束任务

如果你启用了开机自启，手动结束后下次开机仍会自动启动。若要取消开机自启，请删除启动目录中的 `CSUAutoLogin.lnk`。

## Clash 额外配置

如果开启了 Clash 的 TUN 模式，校园网登录页可能打不开。这通常是因为：

- 系统网络探测请求被 TUN 接管，校园网网关无法拦截并重定向到认证页
- 校园网认证域名被公共 DNS 解析失败，或被 Fake-IP 处理成假地址

解决思路是：

- 放行系统网络探测域名
- 放行校园网认证域名
- 让校园网认证域名使用系统 DNS 解析
- 让校园网认证域名走直连

如果你使用的是带 `Script.js` 的 Clash 配置，可以按下面方式调整。

### fake-ip-filter

把这些域名加入 `fake-ip-filter`：

```javascript
"fake-ip-filter": [
  "*.msftconnecttest.com",
  "*.msftncsi.com",
  "captive.apple.com",
  "+.edu.cn"
]
```

如果你知道学校认证域名更精确，优先把 `+.edu.cn` 换成具体域名后缀。

### nameserver-policy

让校园网认证域名走系统 DNS：

```javascript
"nameserver-policy": {
  "+.edu.cn": "system"
}
```

如果 `"system"` 不可用，也可以改成学校实际分配的 DNS 地址。

### rules

让校园网相关域名直连：

```javascript
const rules = [
  "DOMAIN-SUFFIX,edu.cn,DIRECT",
  "DOMAIN-SUFFIX,apple.com,DIRECT"
]
```

如果你的配置里不是直接写 `DIRECT`，而是用了自定义直连策略组，把 `DIRECT` 替换成你的直连策略名即可。

### 建议

如果你只是偶尔需要打开校园网认证页，最简单的方法仍然是临时关闭 TUN，再完成认证，之后重新打开。
