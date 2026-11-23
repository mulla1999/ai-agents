// Labels for profile fields and their choices. The backend's English label is the fallback.

const fieldLabels: Record<string, Record<string, string>> = {
  hi: {
    state: "राज्य", age: "उम्र", occupation: "मुख्य काम", gender: "लिंग", annual_family_income: "परिवार की सालाना आय (₹)",
    social_category: "सामाजिक वर्ग", residence: "गाँव या शहर", has_bank_account: "बैंक / डाकघर बचत खाता है",
    is_income_tax_payer: "परिवार में किसी ने पिछले साल आयकर भरा", is_government_employee: "सरकारी कर्मचारी या पेंशनभोगी",
    owns_cultivable_land: "परिवार के नाम खेती की ज़मीन है", is_bpl: "BPL सूची में परिवार", is_studying_post_matric: "कक्षा 11 या उससे ऊपर पढ़ रहे हैं",
    plans_new_business: "नया व्यवसाय शुरू करना चाहते हैं", is_widow: "विधवा", has_disability: "दिव्यांगता",
    disability_percent: "दिव्यांगता प्रतिशत (प्रमाणपत्र के अनुसार)", is_pregnant_or_lactating: "गर्भवती हैं या स्तनपान करा रही हैं",
    ration_card: "राशन कार्ड का प्रकार", has_pucca_house: "परिवार का अपना पक्का घर है", has_lpg_connection: "घर में LPG गैस कनेक्शन है",
    land_holding_hectares: "परिवार की खेती की ज़मीन (हेक्टेयर; 1 हेक्टेयर ≈ 2.5 एकड़)", has_epf_esic_or_nps: "काम से EPF/PF, ESIC या NPS है",
    has_paid_income_tax: "आपने खुद कभी आयकर भरा है", current_class: "अभी किस कक्षा में पढ़ रहे हैं (1 से 12)",
    is_pregnant: "अभी गर्भवती हैं", owns_house: "परिवार का अपना घर है", has_electricity_connection: "घर में अपना बिजली कनेक्शन (मीटर) है",
    main_earner_died: "परिवार के मुख्य कमाने वाले सदस्य की हाल के वर्षों में मृत्यु हुई है",
  },
};

const optionLabels: Record<string, Record<string, string>> = {
  en: {
    obc: "OBC", sc: "SC", st: "ST", agricultural_labourer: "Agricultural labourer", unorganised_worker: "Unorganised worker",
    self_employed: "Self-employed", aay: "Antyodaya (AAY)", phh: "Priority Household (PHH)", non_priority: "Other ration card",
  },
  hi: {
    male: "पुरुष", female: "महिला", transgender: "ट्रांसजेंडर", general: "सामान्य", obc: "OBC", sc: "SC", st: "ST",
    farmer: "किसान", agricultural_labourer: "खेतिहर मज़दूर", artisan: "कारीगर", unorganised_worker: "असंगठित मज़दूर",
    salaried: "नौकरी", self_employed: "स्व-रोज़गार", student: "विद्यार्थी", homemaker: "गृहिणी", unemployed: "बेरोज़गार",
    retired: "सेवानिवृत्त", other: "अन्य", rural: "गाँव", urban: "शहर", street_vendor: "रेहड़ी-पटरी विक्रेता",
    construction_worker: "निर्माण मज़दूर", domestic_worker: "घरेलू कामगार", fisher: "मछुआरा", aay: "अंत्योदय (AAY)",
    phh: "प्राथमिकता परिवार (PHH)", non_priority: "अन्य राशन कार्ड", none: "कोई नहीं",
  },
};

function titleCase(value: string): string {
  return value
    .split("_")
    .map((word) => (word === "and" ? word : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(" ");
}

export function fieldLabel(lang: string, name: string, fallback: string): string {
  return fieldLabels[lang]?.[name] ?? fallback;
}

export function optionLabel(lang: string, value: string): string {
  return optionLabels[lang]?.[value] ?? optionLabels.en[value] ?? titleCase(value);
}
