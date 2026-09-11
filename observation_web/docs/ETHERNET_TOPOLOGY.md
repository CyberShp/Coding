# 以太网拓扑

入口：设备 → 以太网拓扑。所有现有存储自动列入；交换机通过页面上的“交换机管理”添加、编辑或删除。采集使用 SSH，沿用现有存储凭据；交换机独立保存连接配置。

## 功能与操作

- 点击“采集全部设备”顺序采集当前已添加设备，也可选中单台设备采集。
- 点击设备展开卡件/位置和端口，点击连线查看两端端口、来源、时间。
- 自动关系来自华为 VRP LLDP 邻居；名称不能单独决定真实连线。按设备身份、管理地址和端口 MAC 对应两端，冲突或无法对应时标记待核实。
- 同一物理端口对的双向邻居报告合成一条连接；多条不同端口的并行连接保留。
- 存储直连或未提供邻居信息的设备可以“人工确认接线”。需要先采集两端端口；记录确认人和时间，支持撤销。人工记录与 LLDP 证据分开保留；同一端口指向不同对端会标记冲突。
- 灰色/虚线表示过期或待核实；归属线为点线。展开视图中的归属关系不是网线。
- SSH 采集为用户触发。页面每 30 秒刷新已保存视图，不自动执行设备命令。成功结果超过 5 分钟标记过期。

## 采集边界

首版集中适配以下只读命令：

| 设备 | 命令 | 信息 |
| --- | --- | --- |
| 华为 VRP 交换机 | `display interface brief` | 物理端口及状态 |
| 华为 VRP 交换机 | `display lldp local` | 本机设备标识 |
| 华为 VRP 交换机 | `display lldp neighbor` | 直接邻居及远端端口 |
| 华为 OceanStor 存储 | `show port general physical_type=ETH` | 端口定位、状态、MAC、可用速率 |
| 华为 OceanStor 存储 | `show system general` | 设备名称 |

交换机接口表不包含速率时显示“速率未知”。OceanStor 的 IOM 定位归为卡件、NET 定位归为板载口；其他定位保留原值并标记位置待核实，具体型号需核对。逻辑聚合接口不会当作一根物理网线。

不启用 LLDP、不修改端口、不切换设备配置。命令拒绝、权限不足、格式不认识、输出截断都属于采集失败。失败保留上次完整结果及其原始成功时间，标记过期；明确的空邻居结果更新自动关系。

每台设备 85 秒关闭 SSH 连接的看门狗覆盖交互会话等待；采集并发上限 4，采集槽等待上限 5 秒。持久化采集标记和条件更新防止旧请求覆盖新结果。设备地址/连接身份变化会清理相应快照和人工记录，删除设备同时清理。

**尚未现场验证华为各型号命令兼容性和实际接线准确性。存储到存储的自动物理邻居发现未实现；该场景由人工确认接线覆盖。** 不用同网段、ARP 或 MAC 转发表推断直连。

## 导航

一级入口为总览、设备、告警、监测与测试、设置。相关页面收纳为页签；原路由保留。帮助与反馈位于右上角。

## 离线验证

`tests/fixtures/topology/` 全部是明确编写的模拟输出，不是设备采样。

```sh
# observation_web 目录
python3 -m pytest tests/test_topology.py tests/test_api_arrays.py -q
# frontend 目录
npm run test:run -- tests/unit/topology.spec.js
npm run build
```

覆盖端口解析、LLDP 空/截断输出、身份冲突、端口 MAC 对应、双向去重、并行链路、过期/失败、人工直连、权限、设备变更和数据库迁移。浏览器验收使用隔离测试库及模拟采集，不连接任何设备。

## 命令依据

- [华为 VRP LLDP 命令及邻居字段](https://support.huawei.cn/enterprise/en/doc/EDOC1100515417/556971e0/lldp-configuration-commands)
- [华为接口基础配置命令](https://info.support.huawei.com/enterprise/en/doc/EDOC1100333403/cdd85713/basic-interface-configuration-commands)
- [OceanStor 以太网端口查询命令](https://info.support.huawei.com/hedex/api/pages/EDOC1100214752/YEP0509J/16/resources/basic_block_cli_manage.html)

这些文档提供命令和字段依据，不代表所有华为型号都已经适配或经过真机测试。
