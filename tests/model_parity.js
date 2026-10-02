// Prints site/model.js results for the cases in argv[2] (see test_model_js.py).
const fs = require("node:fs");
const M = require("../site/model.js");
const {D, cases} = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
console.log(JSON.stringify(cases.map(c => { const r = M.price(D, c); return r ? r.hit : null; })));
