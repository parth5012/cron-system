# texure MCP probe report

Passed 19/19 in 2.1s

| check | tool | latency | detail |
|---|---|---|---|
| handshake initialize | protocol | 3.3ms | proto=2024-11-05 server={'name': 'texure-server', 'version': '0.1.0'} |
| ping | protocol | 0.2ms | ping ok |
| exactly 6 frozen tools | protocol | 0.7ms | device_tree, tap, type, keypress, screenshot, wait_for |
| fetch UI tree | device_tree | 4.0ms | rev=42 nodes=2 window=com.velavoice/.MainActivity |
| tap node with fresh rev | tap | 2.4ms | {"ok":true} |
| type into editable | type | 4.9ms | {"ok":true} |
| keypress ENTER | keypress | 2.6ms | {"ok":true} |
| keypress BACK | keypress | 2.2ms | {"ok":true} |
| screenshot PNG decode | screenshot | 2.7ms | png 86 bytes, magic ok |
| wait_for immediate hit | wait_for | 3.7ms | {"ok":true,"rev":44} |
| wait_for timeout -> ok:false | wait_for | 1004.6ms | {"hint":"re-fetch device_tree and re-plan","last_rev":44,"ok":false,"tree":{"nodes":[{"bounds":[12,340,108,56],"cd":null,"children":[],"clickable":true,"cls":"android.widget.Button","editable":false,"id":"btn_send","inde…(502 chars) |
| stale rev -> NODE_OUTDATED | tap | 2.7ms | NODE_OUTDATED: tree refreshed since reference; re-run /ui-tree; re-run device_tree, re-target |
| unknown tool -> -32602 | protocol | 0.5ms | Invalid params: Unknown tool: nope |
| daemon survives tool errors | device_tree | 2.2ms | daemon still serving |
| missing config -> NO_CONFIG | device_tree | 4.9ms | NO_CONFIG: no config file or env vars; create ~/.config/texure/config.toml or set TEXURE_URL/TEXURE_TOKEN |
| dead port -> OFFLINE | device_tree | 6.8ms | OFFLINE: device unreachable; same LAN? app open? fg service alive? |
| wrong token -> AUTH_FAILED | device_tree | 11.4ms | AUTH_FAILED: token mismatch; re-paste fresh token from overlay |
| verbose:true full JSON payload | device_tree | 3.2ms | {"bridge_url":"http://127.0.0.1:44425","error":{"code":"AUTH_FAILED","hint":"re-paste fresh token from overlay","message":"token mismatch"},"http_status":401,"w…(179 chars) |
| malformed JSON -> -32700 | protocol | 2.5ms | parse error -32700 |
