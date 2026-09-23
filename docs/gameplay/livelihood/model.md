# 常驻经营域：模型

`Residence`：居所 ID、玩家、地点、等级、租期、维护状态、休整次数、内容版本。

`FieldPlot`：地块 ID、所有者/宗门、作物键、种子与肥料锁定、播种/成熟时间、维护次数、产量快照、状态、operation ID。

`TownCommission`：委托键、业务日、需求物/服务、库存、报酬、地方名望、状态和内容版本。

`LivelihoodOrder`：订单 ID、委托人、承接人、服务键、材料/报酬锁定、期限、交付质量、状态和 operation ID。

`TradeRoute`：路线键、角色、业务日、货物锁定、起终点、风险池、到达时间、报酬、状态和 operation ID。

`PublicProject`：地区、业务周、项目键、资源目标、逐资源进度、累计贡献点、状态、完成效果窗口与版本快照。当前实现每周只物化一个项目，目标采用文档要求的最小规模。

`ProjectContribution`：项目、角色、资源键、资源数量、贡献点和 operation ID；每笔最多 30 点，资源扣除与进度写入同一事务。

`ProjectReward`：项目、角色、贡献资格、奖励快照和结算 operation ID；`(project_id, player_id)` 唯一，奖励不得包含修为、突破材料或战斗属性。

`LocalReputation`：角色、地区键、名望 0–1000、服务信誉 0–100、当日配额、版本。名望和信誉不可交易、不可直接换修为、不可作为跨境突破前置。
