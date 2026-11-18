/**
 * BAR ST. VINCENT | 对客显示文案（界面文案唯一编辑入口）
 * ================================================================
 * AI 维护指引：修改菜单上“现成的按钮文字 / 导航 / 提示语 / 法律声明”，只改这里。
 * 每项格式 key: ['中文', 'English']，请勿更改 key，避免 app.js 找不到文案。
 * 商品名称、价格、风味故事与套餐信息不在本文件；它们来自 V9 对客数据库接口。
 * 重要：中英文均为顾客可见文字，避免加入开发、试运行、数据库术语。
 * 关键字段：notice 首屏引导；legal 酒精声明；rec* 选酒推荐；cart* 选酒清单。
 * 推荐不采用销量或 NPS 排名；不要加入“最受欢迎”等没有事实依据的表述。
 * ================================================================
 */
window.BSV_MENU_COPY = Object.freeze({
 brandSub:['让今夜有一点不同','A LITTLE SOMETHING EXTRA'],menu:['酒单','Menu'],guide:['帮我选','Find a Drink'],
 store:['选择门店','Choose a bar'],search:['找酒款、口味或小食','Find a drink, flavor or bite'],searchBubble:['说说您想喝什么…','What are you in the mood for?'],searchBubbleLabel:['搜索酒名、口味或小食','Search drinks, flavors and bites'],searchClose:['收起搜索','Close search'],searchClear:['清除搜索','Clear search'],all:['全部','All'],
 notice:['挑一杯喜欢的，剩下的交给调酒师。','Find something you love. Our bartender will take care of the rest.'],
 ask:['到店询价','Ask in bar'],selectedPrice:['本店价格','Bar price'],listedPrice:['统一标价','Menu price'],bundleMenuPrice:['套餐参考价','Set reference price'],regionalPrice:['区域参考','Regional price'],corePrice:['核心参考','Core price'],
 planned:['即将呈现','Coming soon'],availability:['点单前，请与调酒师确认供应及优惠。','Please confirm availability and offers with our bartender.'],
 detail:['看看这款','Discover'],flavor:['喝起来怎么样','What to expect'],story:['这一杯的故事','The story'],
 ingredients:['这一份包含','What’s included'],choices:['如何选择','Your choices'],notes:['贴心提示','Good to know'],
 add:['加入我的选酒单','Add to my list'],previewOnly:['想了解这份套餐？欢迎问问调酒师。','Ask our bartender about this upcoming set.'],
 productAsk:['想了解这一款？欢迎请调酒师介绍。','Ask our bartender about this item.'],
 cart:['我的选酒单','My Selection'],cartNote:['把想喝的酒款加入清单，选好后请调酒师为您下单。','Keep your favorites here, then ask our bartender to place the order.'],
 receipt:['请调酒师为您下单','Ask the bartender to order'],receiptInstruction:['请将此页面展示给调酒师，让调酒师为您下单。','Please show this page to our bartender, who will place your order.'],selectionHeading:['您挑选的酒款','Your selection'],
 continue:['继续看看','Keep exploring'],back:['返回修改','Make changes'],checkStore:['重新确认当前门店','Confirm current bar'],
 emptyCart:['还没有挑选酒款。先去看看吧。','Nothing here yet. Find something you love.'],
 unavailable:['还没有找到合您口味的，不妨换个词试试。','Nothing quite matches. Try another search.'],clear:['查看全部酒单','See full menu'],
 recTitle:['今晚，想喝点什么？','What feels right tonight?'],recSub:['不必熟悉每一款酒。告诉我们您偏爱的味道，就从这里开始。','No need to know every cocktail. Follow your taste.'],
 q1:['您想喝','What would you prefer?'],q2:['您偏爱的口味','Which flavor calls to you?'],q3:['今晚的心情','What is tonight for?'],
 both:['都可以','Either'],yes:['含酒精','Alcoholic'],no:['无酒精','Alcohol-free'],
 fresh:['清爽轻盈','Fresh & light'],fruit:['果香明亮','Bright & fruity'],sweet:['柔和甜润','Soft & sweet'],strong:['醇厚有层次','Rich & layered'],
 relax:['慢慢品味','Savor slowly'],social:['和朋友聊聊','With friends'],exploreTaste:['想来点新鲜的','Try something new'],
 recResults:['不妨从这几杯开始','A Few Ideas for You'],recCaution:['依照您选择的口味，为您找到了几款不同的表达。','A few ideas drawn from the flavors you chose.'],
 recRefresh:['再换一组','Show me a few more'],recLoading:['正在翻开下一页酒单…','Turning to a new page…'],
 alcohol:['含酒精','With alcohol'],noAlcohol:['无酒精','Alcohol-free'],unknown:['酒精信息请咨询调酒师','Ask about alcohol content'],
 detailNote:['如有过敏、忌口或特别偏好，点单前请告诉调酒师。','Please mention any allergies or preferences before ordering.'],
 storeChange:['您切换了门店，请向当前门店的调酒师出示选酒单。','You changed bars. Please show this selection to the bartender at your chosen location.'],
 legal:['乐享美酒需适量，未成年人禁止饮酒。','Enjoy responsibly. Alcohol is not for minors.'],
 count:['款','choices'],loadError:['酒单暂时没有打开。您可以再试一次，或请调酒师帮忙。','We couldn’t open the menu. Try again or ask our bartender.'],
 retry:['重新打开酒单','Try again'],onlyChinese:['欢迎向调酒师了解更多风味细节。','Ask our bartender for the full flavor story.'],
 approxTotal:['已标价商品小计','Subtotal of priced items'],unpricedCart:['另有{n}份商品需到店询价。','{n} item(s) require a price confirmation.'],totalNote:['各店使用统一菜单标价；实际优惠及付款金额以调酒师确认为准。','Menu prices are the same at all bars. The bartender will confirm offers and final payment.'],
 atCounter:['此清单尚未下单或付款。调酒师会与您确认酒款、价格及优惠。','This list is not an order or payment. Our bartender will confirm your drinks, prices and offers.'],
 listPriceNote:['套餐参考价','Set reference price'],
 confirm:['这份尚未开放选择','This set is not yet available'],
 itemNeedConfirm:['价格请向调酒师确认','Please ask about the price'],
 fallbackNotice:['当前展示已发布的备用菜单，供应与实际价格请以门店确认为准。','A previously published menu is shown. Please confirm availability and prices with staff.']
});
