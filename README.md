# طلبك | Talabak

مساعد عربي/إنجليزي لخدمة طلبات متجر تجريبي: حالة الطلب، الإرجاع، الاستبدال ومواعيد الفرع. ينفّذ إجراءات محفوظة محليًا بعد فحص صلاحية الجلسة وتأكيد المستخدم للإجراء المحدد.

**إعداد:** تركي أحمد الصليع  
**البرنامج:** SDAIA Academy — SDA-AIE-213, LLM Application Engineering  
**تواريخ الدفعة:** لم تُزوَّد بعد؛ يلزم إدراج التواريخ الصحيحة قبل التسليم.  
**المسار:** D — Retail order support  
**المرجع:** [موقع الدورة](https://mohammadyusif.github.io/llm-application-engineering/) · [متطلبات المشروع](https://mohammadyusif.github.io/llm-application-engineering/capstone.html) · [SDAIA Academy](https://github.com/SDAIAAcademy)

## التشغيل

افتح `Talabak_Capstone.ipynb` في Jupyter أو ارفع **الدفتر وحده** إلى Google Colab، ثم اختر **Runtime → Run all**. يتضمن الدفتر نسخة مضغوطة من ملفات التطبيق والبيانات والاختبارات؛ ينشئ مجلد تشغيل جديدًا، يثبت المكتبات المقيدة في `requirements.txt`، ويشغّل المحاكي محليًا. لا يحتاج إلى مفتاح مزود أو GPU. تثبيت المكتبات أول مرة يحتاج اتصالًا بالإنترنت. النجاح داخل Colab لا يُدَّعى إلا بعد توثيق تشغيله هناك.

يصل الدفتر إلى محادثة تفاعلية وأربع عروض واختبارات وتقارير قابلة للفحص. مخرجات الاختبارات والنتائج داخل الدفتر هي الدليل؛ وجود الخلايا وحده لا يثبت نجاح تشغيلها.

للتشغيل المحلي من مجلد الحزمة باستخدام Python 3.12:

```console
python -m pip install -r requirements.txt
python scripts/run_all.py
python scripts/serve.py
```

يفتح الأمر الأخير الواجهة على [127.0.0.1:8765](http://127.0.0.1:8765). نتائج التحقق تُحفظ في `artifacts/` والتقريرين `EVALUATION_REPORT.md` و`BENCHMARKS.md`. السجل المحلي للعرض داخل `runtime/`؛ بياناته اصطناعية وتبقى بين مرات تشغيل الواجهة.

## تجربة سريعة

الجلسة الافتراضية عميل تجريبي `CUST-A`؛ هذه هوية عرض محلية، وليست تسجيل دخول إنتاجيًا.

| اكتب | السلوك المقصود |
|---|---|
| وين وصل طلبي ORD-1002؟ | يعرض حالة الطلب المملوك للجلسة. |
| أبغى أرجع الطلب ORD-1001 لأن المنتج غير مناسب | يفحص سياسة المتجر ويعرض الإجراء للتأكيد. |
| موافق | ينفّذ الإجراء الذي عُرض في الرسالة السابقة فقط. |
| أبغى استبدل ORD-1001 بالمنتج SKU-H200 | يفحص الملكية والأهلية والسعر والمخزون قبل التأكيد. |
| احجز لي موعد SLOT-001 | يفحص السعة ثم يطلب التأكيد. |
| ما مواعيد المتجر؟ | يجيب من بيانات المتجر التجريبية. |
| أريد التحدث إلى موظف | ينهي المسار الآلي محليًا؛ لا يرسل رسالة إلى شخص خارج التطبيق. |

جرّب كل إجراء جديد بجلسة/قاعدة عرض جديدة إذا سبق إنشاء معالجة لنفس الطلب. التكرار لا ينشئ إرجاعًا أو حجزًا ثانيًا.

## ماذا يثبت التشغيل المحلي؟

المشروع يستدعي OpenAI SDK فعليًا عبر HTTP إلى **محاكي على loopback**. تعيد البوابة أشكال `tool_calls` و`usage` و`json_schema`، وتدعم أعطالًا مقصودة لاختبار الإصلاح وإعادة المحاولة والتحويل الاحتياطي. أسماء primary/open_weight/judge في الإعدادات تصف مسارات محاكاة.

| نوع الدليل | الحالة التي يجب قراءتها |
|---|---|
| عقود SDK والأدوات وPydantic والحواجز والبوابة والتخزين | تثبتها نتائج الاختبارات المحلية المرفقة عند نجاحها. |
| تكلفة المحاكي | الإنفاق على مزود خارجي صفر؛ `simulated_cost_usd` تقدير بتعرفة تعليمية منفصلة. |
| جودة نموذج تجاري مقابل نموذج مفتوح الأوزان | تحتاج تشغيل النموذجين الحقيقيين على المجموعة نفسها؛ المحاكي لا يثبتها. |
| معايرة المقيم | تحتاج تصنيفات بشرية حقيقية وκ محسوبة؛ النموذج/المساعد لا يملأ وسوم البشر. |
| تعادل الاستضافة الذاتية | يحتاج throughput مقاسًا على عتاد محدد؛ زمن المحاكي ليس throughput لنموذج. |
| مراجعة الزملاء وتواريخ الدفعة | تبقى معلومات خارجية حتى تتوفر أدلتها. |

التقرير الناتج عن كل تشغيل يحدد ما نجح وما فشل وما لم يُقَس. لا يتضمن المشروع ضمانًا للدرجة. النشر على GitHub أو التسليم للمنصة مؤجل حتى يطلب صاحبه ذلك صراحة.

## البنية

```text
Talabak_Capstone.ipynb   دفتر مستقل يحوي الحزمة ويعيد تشغيل الأدلة
config/                أسماء المسارات والحدود والتعرفة التعليمية
data/                  متجر اصطناعي ومجموعات التقييم الأصلية
prompts/               تعليمات وعقود حكم ذات إصدارات
talabak/               حد النموذج، المحاكي، السياسات ومسار التطبيق
tests/                 اختبارات العقود والسلامة والسلوك
scripts/               تشغيل التقييم والمعايرة وبناء الدفتر
docs/                  القرارات وحدود السياق وأدلة التشغيل
```

راجع [DECISIONS.md](docs/DECISIONS.md) للأسباب والمفاضلات و[CONTEXT_BUDGET.md](docs/CONTEXT_BUDGET.md) لحدود السياق وطريقة القياس. البيانات والأسعار والسياسات والعملاء والطلبات **اصطناعية**، والساعة المرجعية للمتجر مثبتة داخل البيانات كي تتكرر اختبارات الأهلية والمواعيد.

## English quick guide

Talabak is an Arabic/English Track D retail order-support capstone by **تركي أحمد الصليع**, built for SDAIA Academy's SDA-AIE-213 programme. It demonstrates order status, returns, exchanges and store appointments using fictional data and a local SQLite store. Cohort dates are awaiting confirmation.

Open the standalone notebook and choose **Run all**. It extracts its embedded source bundle, installs pinned dependencies and starts a local simulator without provider credentials or a GPU. The first dependency installation needs network access. The interactive conversation, executed tests and run-derived reports form the local evidence.

All configured model routes are simulated. External provider spend is zero; illustrative token-cost estimates are labelled separately. Commercial/open-weight quality, genuine human calibration, measured self-host throughput and actual fresh-Colab execution must each carry their own evidence before being claimed.

## Attribution

The course [Murshid reference implementation](https://github.com/MohammadYusif/llm-application-engineering) informed the model boundary, layered pipeline, repair loop, evaluation and cost-evidence disciplines. Talabak uses its own retail domain, tools, policy data, guard cases and evaluation data. Course or student benchmark numbers are not reused as this project's results. See the separate course audit for exact requirement sources and the differences between Capstone and Lab 5's golden-set sizes.
