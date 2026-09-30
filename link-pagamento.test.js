'use strict';
// Testes das funções puras. Não usa rede e não chama o Pagar.me.
const assert = require('assert');
const { parseValor, parseComando, nomeDoLink, montarPayload } = require('./link-pagamento');

assert.strictEqual(parseValor('8.580,00'), 858000);
assert.strictEqual(parseValor('8580'), 858000);
assert.strictEqual(parseValor('8580.50'), 858050);
assert.strictEqual(parseValor('R$ 1.234,5'), 123450);
assert.strictEqual(parseValor('1.234'), 123400);
assert.strictEqual(parseValor('abc'), null);
assert.strictEqual(parseValor('0'), null);
assert.strictEqual(parseValor('-5'), null);

let d = parseComando('/link Maria Silva; GRU-LIS / LIS-GRU; 8.580,00; 10');
assert.deepStrictEqual(d, { cliente: 'Maria Silva', itinerario: 'GRU-LIS / LIS-GRU', valorCent: 858000, parcelas: 10 });
assert.deepStrictEqual(parseComando('/link@MeuBot Ana\nGIG-MIA\n1000\n3'), { cliente: 'Ana', itinerario: 'GIG-MIA', valorCent: 100000, parcelas: 3 });
assert.ok(parseComando('/link Maria; GRU-LIS; 100').erro);          // faltou campo
assert.ok(parseComando('/link Maria; GRU-LIS; xx; 3').erro);        // valor inválido
assert.ok(parseComando('/link Maria; GRU-LIS; 100; 0').erro);       // parcelas 0
assert.ok(parseComando('/link Maria; GRU-LIS; 100; 13').erro);      // acima do máximo
assert.ok(parseComando('/link Maria; GRU-LIS; 100; 2.5').erro);     // parcelas não inteiras

assert.strictEqual(nomeDoLink('Maria Silva', 'GRU-LIS'), 'Maria Silva - GRU-LIS');
const longo = nomeDoLink('Maria Silva', 'GRU-LIS / LIS-GRU / LIS-MAD / MAD-LIS / MAD-GRU / GRU-SCL / SCL-GRU');
assert.ok(longo.length <= 64, `nome com ${longo.length} caracteres`);
assert.ok(longo.startsWith('Maria Silva - GRU-LIS'));
assert.ok(nomeDoLink('X'.repeat(80), 'GRU-LIS').length <= 64);

const p = montarPayload(d, { validadeDias: 7 });
assert.strictEqual(p.name, 'Maria Silva - GRU-LIS / LIS-GRU');
assert.strictEqual(p.type, 'order');
assert.strictEqual(p.max_paid_sessions, 1);
assert.strictEqual(p.expires_in, 10080);
assert.deepStrictEqual(p.payment_settings.accepted_payment_methods, ['credit_card']);
const s = p.payment_settings.credit_card_settings.installments_setup;
assert.strictEqual(s.max_installments, 10);
assert.strictEqual(s.free_installments, 10);   // sem juros em todas as parcelas
assert.strictEqual(s.interest_rate, 0);
assert.strictEqual(s.amount, 858000);
assert.strictEqual(p.cart_settings.items[0].amount, 858000);
assert.strictEqual(p.cart_settings.items[0].default_quantity, 1);
assert.strictEqual(montarPayload(d, { validadeDias: 0 }).expires_in, undefined);

console.log('todos os testes passaram');

// autorização: o admin sempre pode; os outros só depois de aprovados ou listados
const { autorizado, config } = require('./link-pagamento');
const cfg = { ...config(), admin: '695765510', autorizados: ['42'] };
assert.ok(autorizado(695765510, cfg));
assert.ok(autorizado(42, cfg));
assert.ok(!autorizado(99, cfg));
console.log('ok');
