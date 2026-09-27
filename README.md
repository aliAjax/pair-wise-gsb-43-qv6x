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
- `POST /api/qualifications`：供应商提交资格预审材料（被驳回/撤销后可重新提交）
- `POST /api/qualifications/review`：采购方审核，`decision` 为 `approved`/`rejected`，驳回必须填写审核意见
- `POST /api/qualifications/revoke`：开标前撤销已通过资格，须写明原因；已存在的未开标投标保留
- `POST /api/bids`、`POST /api/bids/withdraw`、`POST /api/bids/disqualify`
- `POST /api/tenders/open`：截止后开标并核验承诺哈希；开标时资格已非 `approved` 的投标保留并标记为 `qualification_failed`（写明原因），不参与评分与授标
- `GET /api/tenders/{id}`：项目详情返回每家供应商的资格状态、审核意见与冻结记录（`qualifications[].events`），采购/监督/审计看全部，供应商仅看本人提交记录
- `POST /api/conflicts`、`POST /api/evaluations`
- `POST /api/clarifications`、`POST /api/clarifications/answer`
- `POST /api/complaints`、`POST /api/complaints/resolve`
- `POST /api/tenders/award`：锁定评分轮次并保存排名快照

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖完整开标授标、截止前正文隐藏、利益冲突、重复评分覆盖、投诉重评、角色权限和资格预审（投标门槛、驳回重提、开标前撤销保留投标、开标标记未通过原因、评分授标排除、冻结记录追溯）。

## 资格预审规则

- 资格记录按「项目 × 供应商」唯一，状态流转：`pending`（待审核）→ `approved`（通过）/ `rejected`（驳回，可重新提交）；`approved` → `revoked`（开标前撤销，可重新提交）。
- 只有 `approved` 的供应商可以提交或修改投标；资格被撤销后不能再改标。
- 撤销资格不删除已提交的未开标投标：开标时该投标通过哈希完整性校验后保留，状态置为 `qualification_failed`，并在 `status_reason` 写明「资格已被撤销（原因）」，评分和授标均排除。若供应商在开标前重新提交并复核通过，投标恢复正常开标。
- 开标后发现的资格问题走废标流程（`POST /api/bids/disqualify`），撤销资格接口在开标后拒绝执行。
- 每次资格变更（提交/重提/通过/驳回/撤销）都追加一条不可变冻结记录到 `qualification_events`，同时写入全局 `timeline` 审计流。

## 局限

供应商与请求用户没有绑定校验，身份仍依赖请求头；投标正文虽然按接口阶段隐藏，但数据库本身未加密；评分规则适合演示，资格预审仅覆盖单轮「提交—审核—撤销」，不覆盖多轮评审、保证金、电子签名和采购法规差异。
