// Labels for profile fields and their choices. The backend's English label is the fallback.

const fieldLabels: Record<string, Record<string, string>> = {
  hi: {
    state: "राज्य", age: "उम्र", occupation: "मुख्य काम", gender: "लिंग", annual_family_income: "परिवार की सालाना आय (₹)",
    social_category: "सामाजिक वर्ग", residence: "गाँव या शहर", has_bank_account: "बैंक / डाकघर बचत खाता है",
    is_income_tax_payer: "परिवार में किसी ने पिछले साल आयकर भरा", is_government_employee: "सरकारी कर्मचारी या पेंशनभोगी",
    owns_cultivable_land: "परिवार के नाम खेती की ज़मीन है", is_bpl: "BPL सूची में परिवार", is_studying_post_matric: "कक्षा 11 या उससे ऊपर पढ़ रहे हैं",
    plans_new_business: "नया व्यवसाय शुरू करना चाहते हैं", is_widow: "विधवा", has_disability: "दिव्यांगता",
  },
};

const optionLabels: Record<string, Record<string, string>> = {
  en: {
    obc: "OBC", sc: "SC", st: "ST", agricultural_labourer: "Agricultural labourer", unorganised_worker: "Unorganised worker",
    self_employed: "Self-employed",
  },
  hi: {
    male: "पुरुष", female: "महिला", transgender: "ट्रांसजेंडर", general: "सामान्य", obc: "OBC", sc: "SC", st: "ST",
    farmer: "किसान", agricultural_labourer: "खेतिहर मज़दूर", artisan: "कारीगर", unorganised_worker: "असंगठित मज़दूर",
    salaried: "नौकरी", self_employed: "स्व-रोज़गार", student: "विद्यार्थी", homemaker: "गृहिणी", unemployed: "बेरोज़गार",
    retired: "सेवानिवृत्त", other: "अन्य", rural: "गाँव", urban: "शहर",
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
