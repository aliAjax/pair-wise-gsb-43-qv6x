# 公共采购密封投标与评审系统

标准库实现的招标发布、资格预审、密封投标、开标校验收、规则评分、利益冲突、澄清、废标、投诉重评和授标快照服务。

## 运行

要求 Python 3.11+（当前 Python 3.9 环境亦可）。

```bash
python3 app.py --init --seed
python3 app.py
```

默认地址 `http://127.0.0.1:8209`，数据库默认 `public_procurement.db`。

## 主要接口

使用 `X-User`、`X-Role` 请求头。角色有 `procurement`、`vendor`、`evaluator`、`supervisor`、`auditor`、`public`。

- `GET /health`、`GET /api/state`、`GET /api/tenders/{id}`
- `POST /api/vendors`、`POST /api/tenders`、`POST /api/tenders/publish`
- `POST /api/qualifications`、`POST /api/qualifications/review`、`POST /api/qualifications/revoke`
- `POST /api/bids`、`POST /api/bids/withdraw`、`POST /api/bids/disqualify`
- `POST /api/tenders/open`：截止后开标并核验承诺哈希
- `POST /api/conflicts`、`POST /api/evaluations`
- `POST /api/clarifications`、`POST /api/clarifications/answer`
- `POST /api/complaints`、`POST /api/complaints/resolve`
- `POST /api/tenders/award`：锁定评分轮次并保存排名快照

## 资格预审

- 供应商按项目提交资格材料（`POST /api/qualifications`），采购方审核通过（`POST /api/qualifications/review`）后才能投标；被驳回可补正后重新提交。
- 资格被撤销（`POST /api/qualifications/revoke`）时，未开标投标保留并在开标时记为“资格审查未通过”且写明原因，不参与评分和授标。
- `GET /api/tenders/{id}` 返回每家供应商的资格状态、审核意见和变更/冻结记录，每次变更同时写入时间线。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖完整开标授标、截止前正文隐藏、利益冲突、重复评分覆盖、投诉重评、角色权限，以及资格预审的提交审核、撤销冻结和开标标记。

## 局限

供应商与请求用户没有绑定校验，身份仍依赖请求头；投标正文虽然按接口阶段隐藏，但数据库本身未加密；资格预审只覆盖按项目提交、审核与撤销，评分规则适合演示，不覆盖保证金、电子签名和采购法规差异。
