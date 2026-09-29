/**
 * Parsers determinísticos (sem IA) para PDFs de reserva.
 *
 * Formatos suportados:
 *   1) "Visualizar reserva"  - Azul, LATAM/TAM, Gol, American, TAP, Avianca...
 *   2) "Bilhete Eletrônico - Eticket" (portal de agência) - ex.: Air France
 *
 * parseFlightText(texto) devolve um objeto com os dados do voo ou null se não
 * reconhecer o formato (aí o bot cai no plano B com IA / entrada manual).
 */

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

const AIRLINES = {
  // ICAO (3 letras) e IATA (2 caracteres)
  AZU: 'Azul', AD: 'Azul',
  GLO: 'Gol', G3: 'Gol',
  TAM: 'LATAM', LAT: 'LATAM', LA: 'LATAM', JJ: 'LATAM',
  AA: 'American Airlines', AAL: 'American Airlines',
  TAP: 'TAP Air Portugal', TP: 'TAP Air Portugal',
  AV: 'Avianca', AVA: 'Avianca',
  AF: 'Air France', AFR: 'Air France',
  KL: 'KLM', KLM: 'KLM',
  IB: 'Iberia', IBE: 'Iberia',
  UA: 'United', UAL: 'United',
  DL: 'Delta', DAL: 'Delta',
  LH: 'Lufthansa', DLH: 'Lufthansa',
  BA: 'British Airways', BAW: 'British Airways',
  EK: 'Emirates', UAE: 'Emirates',
  QR: 'Qatar Airways', QTR: 'Qatar Airways',
  CM: 'Copa Airlines', CMP: 'Copa Airlines',
  AR: 'Aerolíneas Argentinas', ARG: 'Aerolíneas Argentinas',
  AM: 'Aeroméxico', AMX: 'Aeroméxico',
  AC: 'Air Canada', ACA: 'Air Canada',
  LX: 'Swiss', SWR: 'Swiss',
  ET: 'Ethiopian', ETH: 'Ethiopian',
  TK: 'Turkish Airlines', THY: 'Turkish Airlines',
  SA: 'South African Airways', SAA: 'South African Airways',
  '2Z': 'Voepass', PTB: 'Voepass',
  AZ: 'ITA Airways', ITY: 'ITA Airways',
  UX: 'Air Europa', AEA: 'Air Europa',
  OS: 'Austrian', AUA: 'Austrian',
  SN: 'Brussels Airlines', BEL: 'Brussels Airlines',
  AY: 'Finnair', FIN: 'Finnair',
  EY: 'Etihad', ETD: 'Etihad',
  MS: 'EgyptAir', MSR: 'EgyptAir',
  SQ: 'Singapore Airlines', SIA: 'Singapore Airlines',
  NH: 'ANA', ANA: 'ANA',
  JL: 'Japan Airlines', JAL: 'Japan Airlines',
  CX: 'Cathay Pacific', CPA: 'Cathay Pacific',
  QF: 'Qantas', QFA: 'Qantas',
  KE: 'Korean Air', KAL: 'Korean Air',
  VS: 'Virgin Atlantic', VIR: 'Virgin Atlantic',
  EI: 'Aer Lingus', EIN: 'Aer Lingus',
  LO: 'LOT Polish', LOT: 'LOT Polish',
  SK: 'SAS', SAS: 'SAS',
  H2: 'Sky Airline', SKU: 'Sky Airline',
  JA: 'JetSMART', JAT: 'JetSMART',
  WJ: 'JetSMART',
  LAN: 'LATAM'
};

function airlineFromFlight(flightCode) {
  const code = String(flightCode || '').toUpperCase();
  for (const len of [3, 2]) {
    const p = code.slice(0, len);
    if (AIRLINES[p]) return AIRLINES[p];
  }
  const letters = (code.match(/^[A-Z]+/) || [''])[0];
  return letters || null;
}

const MONTHS = {
  JAN: '01', FEV: '02', MAR: '03', ABR: '04', MAI: '05', JUN: '06',
  JUL: '07', AGO: '08', SET: '09', OUT: '10', NOV: '11', DEZ: '12',
  FEB: '02', APR: '04', MAY: '05', AUG: '08', SEP: '09', OCT: '10', DEC: '12'
};

// "MR", "MRS"... soltos no meio/fim do nome (padrão de sistemas de reserva)
function cleanName(name) {
  return String(name)
    .replace(/\b(MR|MRS|MS|MISS|MSTR)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function itinerary(segs) {
  if (!segs.length) return null;
  return [segs[0].de, ...segs.map((s) => s.para)].join('-');
}

function toDate(ddmmyyyy, hhmm) {
  const [d, m, y] = ddmmyyyy.split('/').map(Number);
  const [hh, mm] = hhmm.split(':').map(Number);
  return new Date(y, m - 1, d, hh, mm);
}

function buildResult({ ida, volta, localizador, passageiros, avisos }) {
  return {
    data_ida: ida[0].dataSaida,
    horario_ida: ida[0].saida,
    itinerario_ida: itinerary(ida),
    data_volta: volta.length ? volta[0].dataSaida : null,
    horario_volta: volta.length ? volta[0].saida : null,
    itinerario_volta: itinerary(volta),
    cia_aerea: airlineFromFlight(ida[0].voo),
    localizador: localizador || null,
    passageiros,
    trechos_ida: ida,
    trechos_volta: volta,
    avisos: avisos || []
  };
}

// ---------------------------------------------------------------------------
// Formato 1: "Visualizar reserva"
// ---------------------------------------------------------------------------

const SEG_RE =
  /(\d{2}:\d{2})\s+(\d{2}\/\d{2}\/\d{4})[\s\S]*?\b([A-Z]{3})\s+([A-Z]{3})\s+Voo\s+([A-Z0-9]+)[\s\S]*?\(([A-Z]{3})\)\s*(\d{2}:\d{2})\s+(\d{2}\/\d{2}\/\d{4})/g;

function parseSegmentsV1(block) {
  const segs = [];
  let m;
  SEG_RE.lastIndex = 0;
  while ((m = SEG_RE.exec(block)) !== null) {
    segs.push({
      saida: m[1],
      dataSaida: m[2],
      de: m[3],
      para: m[4],
      voo: m[5],
      chegada: m[7],
      dataChegada: m[8]
    });
  }
  return segs;
}

function parseVisualizarReserva(text) {
  if (!/Visualizar reserva/i.test(text) && !/Voo\s+[A-Z0-9]+/.test(text)) return null;

  const idxIda = text.search(/\bIDA\b/);
  if (idxIda < 0) return null;
  const idxVolta = text.search(/\bVOLTA\b/);
  const idxPass = text.search(/Passageiros\s*:/);

  const endIda = idxVolta >= 0 ? idxVolta : idxPass >= 0 ? idxPass : text.length;
  const endVolta = idxPass >= 0 ? idxPass : text.length;

  const ida = parseSegmentsV1(text.slice(idxIda, endIda));
  const volta = idxVolta >= 0 ? parseSegmentsV1(text.slice(idxVolta, endVolta)) : [];
  if (!ida.length) return null;

  // "Localizador\nABC123"  (há também "Número da compra", que é outra coisa)
  const loc = text.match(/Localizador\s+([A-Z0-9]{6})\b/);

  // Nome, opcionalmente seguido de "e-ticket: 123...", depois "Ida ... Assentos"
  const passageiros = [];
  if (idxPass >= 0) {
    const re =
      /([A-ZÀ-ÚÇ][A-ZÀ-ÚÇ' .-]+[A-ZÀ-ÚÇ])(?:\s*e-ticket:\s*[\d-]+)?\s*Ida\s*Assentos/g;
    const passText = text.slice(idxPass);
    let p;
    while ((p = re.exec(passText)) !== null) passageiros.push(cleanName(p[1]));
  }

  return buildResult({ ida, volta, localizador: loc && loc[1], passageiros });
}

// ---------------------------------------------------------------------------
// Formato 2: "Bilhete Eletrônico - Eticket" (portal de agência)
// ---------------------------------------------------------------------------

const SEG2_RE = new RegExp(
  '(?!ADT|CHD|INF)([A-Z]{3}) - [^\\n]*\\n(?:[^\\n]*\\n){0,3}?(\\d{2}) ([A-Z]{3}) (\\d{4}) (\\d{2}:\\d{2})' +
    '[\\s\\S]*?' +
    '(?!ADT|CHD|INF)([A-Z]{3}) - [^\\n]*\\n(?:[^\\n]*\\n){0,3}?(\\d{2}) ([A-Z]{3}) (\\d{4}) (\\d{2}:\\d{2})' +
    '[\\s\\S]*?' +
    '\\n([A-Z0-9]{2})\\s+(\\d+?)\\s*(\\d)\\s*([A-Z])\\b',
  'g'
);

function parseSegmentsV2(block) {
  const segs = [];
  let m;
  SEG2_RE.lastIndex = 0;
  while ((m = SEG2_RE.exec(block)) !== null) {
    const mes1 = MONTHS[m[3]];
    const mes2 = MONTHS[m[8]];
    if (!mes1 || !mes2) continue;
    segs.push({
      de: m[1],
      dataSaida: `${m[2]}/${mes1}/${m[4]}`,
      saida: m[5],
      para: m[6],
      dataChegada: `${m[7]}/${mes2}/${m[9]}`,
      chegada: m[10],
      voo: `${m[11]}${m[12]}`,
      _start: m.index,
      _end: m.index + m[0].length
    });
  }
  return segs;
}

// SOBRENOME/NOME MR  ->  NOME SOBRENOME
function nameFromSlash(raw) {
  const s = cleanName(raw.replace(/\s*\n\s*/g, ' '));
  if (s.includes('/')) {
    const [sobrenome, nome] = s.split('/', 2);
    return `${nome.trim()} ${sobrenome.trim()}`.replace(/\s+/g, ' ');
  }
  return s;
}

const TITLE_END = /\b(MR|MRS|MS|MISS|MSTR)$/;
const MIN_PAUSA_MS = 20 * 3600 * 1000; // pausa mínima para contar como "volta"

// "ADT - SOBRENOME/NOME MR" (o nome pode quebrar em até 3 linhas)
function extractPassengersV2(block) {
  const out = [];
  const lines = block.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/(?:ADT|CHD|INF)\s*-\s*([A-ZÀ-ÚÇ][^\n]*\/[^\n]*)$/);
    if (!m) continue;
    let raw = m[1].trim();
    let j = i;
    while (!TITLE_END.test(raw) && j - i < 3) {
      const next = (lines[j + 1] || '').trim();
      // linha da agência/emissão tem minúsculas ou " - ": não é continuação do nome
      if (!next || /[a-zà-ú]/.test(next) || / - /.test(next) || !/^[A-ZÀ-ÚÇ' \/.-]+$/.test(next)) break;
      raw += ' ' + next;
      j++;
    }
    out.push(nameFromSlash(raw));
  }
  return out;
}

// Localizador da companhia (coluna "Loc Cia")
function locatorV2(block) {
  const m = block.match(/Cabine:[^\n]*\n([A-Z0-9]{6})\b/);
  if (m) return m[1];
  const h = block.search(/Loc\s*Cia/i);
  if (h >= 0) {
    const r = block.slice(h).match(/\n([A-Z0-9]{6})\n/);
    if (r && /[A-Z]/.test(r[1])) return r[1];
  }
  return null;
}

function segKey(segs) {
  return segs.map((s) => `${s.dataSaida} ${s.saida} ${s.de}${s.para}`).join('|');
}

function parseEticketAgencia(text) {
  if (!/Bilhete Eletr[oô]nico/i.test(text)) return null;

  // Um bilhete por passageiro (uma página cada), normalmente com os mesmos voos
  const blocks = text
    .split(/Bilhete Eletr[oô]nico\s*-\s*Eticket/i)
    .filter((b) => /(ADT|CHD|INF)\s*-/.test(b));
  if (!blocks.length) return null;

  const passageiros = [];
  for (const b of blocks) {
    for (const nome of extractPassengersV2(b)) {
      if (!passageiros.includes(nome)) passageiros.push(nome);
    }
  }

  const segs = parseSegmentsV2(blocks[0]);
  if (!segs.length) return null;

  // Ida x volta: separa na MAIOR pausa entre trechos que NÃO seja conexão
  // (o PDF marca conexões com "Conexão em: ..."; pausas < 20h também não contam)
  let splitAt = -1;
  let maiorPausa = 0;
  for (let i = 0; i < segs.length - 1; i++) {
    const entre = blocks[0].slice(segs[i]._end, segs[i + 1]._start);
    if (/Conex[aã]o em/i.test(entre)) continue;
    const pausa =
      toDate(segs[i + 1].dataSaida, segs[i + 1].saida) - toDate(segs[i].dataChegada, segs[i].chegada);
    if (pausa >= MIN_PAUSA_MS && pausa > maiorPausa) {
      maiorPausa = pausa;
      splitAt = i;
    }
  }
  const ida = splitAt >= 0 ? segs.slice(0, splitAt + 1) : segs;
  const volta = splitAt >= 0 ? segs.slice(splitAt + 1) : [];

  const avisos = [];

  // Mais de 2 "viagens" separadas (ex.: roteiro com parada longa no meio)
  const viagens =
    1 +
    segs.slice(0, -1).filter((s, i) => {
      const entre = blocks[0].slice(s._end, segs[i + 1]._start);
      if (/Conex[aã]o em/i.test(entre)) return false;
      const pausa =
        toDate(segs[i + 1].dataSaida, segs[i + 1].saida) - toDate(s.dataChegada, s.chegada);
      return pausa >= MIN_PAUSA_MS;
    }).length;
  if (viagens > 2) {
    avisos.push(`Roteiro com ${viagens} viagens separadas: separei ida/volta na maior pausa. Confira os itinerários.`);
  }

  // Bilhetes de outros passageiros com voos diferentes do primeiro?
  for (let k = 1; k < blocks.length; k++) {
    const outros = parseSegmentsV2(blocks[k]);
    if (segKey(outros) !== segKey(segs)) {
      avisos.push(`O bilhete ${k + 1} tem voos diferentes do primeiro. Os dados de voo acima são do bilhete 1.`);
      break;
    }
  }

  return buildResult({ ida, volta, localizador: locatorV2(blocks[0]), passageiros, avisos });
}

// ---------------------------------------------------------------------------
// Formato 3: itinerário "PREPARADO PARA ... CÓDIGO DA RESERVA ... SAÍDA: DIA 07 FEV"
// (datas sem ano: o ano vem da linha "07 FEV 2027  22 FEV 2027 VIAGEM PARA ...")
// ---------------------------------------------------------------------------

const PEQUENAS = new Set(['de', 'da', 'do', 'das', 'dos', 'e']);
function titleCase(name) {
  return String(name)
    .toLowerCase()
    .split(/\s+/)
    .map((w, i) => (i > 0 && PEQUENAS.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ');
}

function parseItinerarioReserva(text) {
  const loc = text.match(/C[ÓO]DIGO DA RESERVA\s+([A-Z0-9]{6})\b/);
  if (!loc || !/SA[ÍI]DA:/.test(text)) return null;

  // Ano de partida (cabeçalho) e passageiros ("PREPARADO PARA")
  const head = text.match(/(\d{2}) ([A-Z]{3}) (\d{4})/);
  let year = head ? Number(head[3]) : new Date().getFullYear();
  let prevMonth = head && MONTHS[head[2]] ? Number(MONTHS[head[2]]) : 0;

  const passageiros = [];
  const pp = text.match(/PREPARADO PARA\s*\n([\s\S]*?)C[ÓO]DIGO DA RESERVA/);
  if (pp) {
    for (const line of pp[1].split('\n')) {
      const n = line.trim();
      if (n && !/\d/.test(n) && !/Dist[âa]ncia/i.test(n)) passageiros.push(titleCase(n));
    }
  }

  const segs = [];
  const blocks = text.split(/SA[ÍI]DA:/).slice(1);
  for (const b of blocks) {
    const d = b.match(/^\s*[^\n]*?(\d{2})\s+([A-Z]{3})\b/);
    const f = b.match(/([A-Z0-9]{2})\s+(\d{1,4})\s*\n?\s*Dura[cç]/);
    const antes = b.split(/Aeronave:/)[0];
    const codes = antes.split('\n').map((l) => l.trim()).filter((l) => /^[A-Z]{3}$/.test(l));
    const hs = b.match(/Partindo [àa]s:\s*(\d{2}:\d{2})/);
    const hc = b.match(/Chegando [àa]s:\s*(\d{2}:\d{2})/);
    if (!d || !f || codes.length < 2 || !hs || !hc || !MONTHS[d[2]]) continue;

    const mes = Number(MONTHS[d[2]]);
    if (mes < prevMonth) year += 1; // virou o ano (ex.: dez -> jan)
    prevMonth = mes;
    const dia = d[1];
    const dataSaida = `${dia}/${MONTHS[d[2]]}/${year}`;
    // o PDF não traz a data de chegada: se chega "antes" de sair, foi no dia seguinte
    let dataChegada = dataSaida;
    if (hc[1] < hs[1]) {
      const nx = new Date(year, mes - 1, Number(dia) + 1);
      dataChegada = `${String(nx.getDate()).padStart(2, '0')}/${String(nx.getMonth() + 1).padStart(2, '0')}/${nx.getFullYear()}`;
    }
    segs.push({
      de: codes[0],
      dataSaida,
      saida: hs[1],
      para: codes[1],
      dataChegada,
      chegada: hc[1],
      voo: `${f[1]}${f[2]}`
    });
  }
  if (!segs.length) return null;

  // Nomes no rodapé de cada trecho ("» Nome ..."), caso o cabeçalho não traga
  if (!passageiros.length) {
    const re = /»\s*([A-Za-zÀ-ÿ' .-]+?)(?=Check-?in|Assento|Sem\s+assento|\d|\n|$)/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      const n = m[1].trim();
      if (n && !passageiros.includes(n)) passageiros.push(n);
    }
  }

  // Ida x volta: maior pausa >= 20h entre trechos
  let splitAt = -1;
  let maior = 0;
  for (let i = 0; i < segs.length - 1; i++) {
    const pausa =
      toDate(segs[i + 1].dataSaida, segs[i + 1].saida) - toDate(segs[i].dataChegada, segs[i].chegada);
    if (pausa >= MIN_PAUSA_MS && pausa > maior) {
      maior = pausa;
      splitAt = i;
    }
  }
  const ida = splitAt >= 0 ? segs.slice(0, splitAt + 1) : segs;
  const volta = splitAt >= 0 ? segs.slice(splitAt + 1) : [];

  const avisos = [];
  const viagens =
    1 +
    segs.slice(0, -1).filter(
      (s, i) =>
        toDate(segs[i + 1].dataSaida, segs[i + 1].saida) - toDate(s.dataChegada, s.chegada) >= MIN_PAUSA_MS
    ).length;
  if (viagens > 2) {
    avisos.push(`Roteiro com ${viagens} viagens separadas: separei ida/volta na maior pausa. Confira os itinerários.`);
  }
  if (!head) avisos.push('Este PDF não traz o ano dos voos: usei o ano atual. Confira as datas.');

  return buildResult({ ida, volta, localizador: loc[1], passageiros, avisos });
}

// ---------------------------------------------------------------------------
// Formato 4: confirmação de HOTEL (ex.: Booking.com)
//   entrada = "data ida", saída = "data volta", horários em branco,
//   itinerário = cidade, cia aérea = nome do hotel, localizador = nº de confirmação
// ---------------------------------------------------------------------------

const MESES_PT = {
  JANEIRO: 1, FEVEREIRO: 2, MARCO: 3, ABRIL: 4, MAIO: 5, JUNHO: 6,
  JULHO: 7, AGOSTO: 8, SETEMBRO: 9, OUTUBRO: 10, NOVEMBRO: 11, DEZEMBRO: 12
};
const DIAS_SEMANA = { DOMINGO: 0, SEGUNDA: 1, TERCA: 2, QUARTA: 3, QUINTA: 4, SEXTA: 5, SABADO: 6 };
const semAcento = (t) => String(t).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();

// O PDF traz só dia + mês + dia da semana. O ano é o que faz o dia da semana
// bater, entre os anos mais próximos de hoje.
function inferYear(dia, mes, diaSemana) {
  const hoje = new Date();
  let melhor = null;
  for (let y = hoje.getFullYear() - 2; y <= hoje.getFullYear() + 3; y++) {
    const d = new Date(y, mes - 1, dia);
    if (d.getMonth() !== mes - 1) continue;
    if (diaSemana !== undefined && d.getDay() !== diaSemana) continue;
    const dist = Math.abs(d - hoje);
    if (!melhor || dist < melhor.dist) melhor = { y, dist };
  }
  return melhor ? melhor.y : null;
}

function parseHotelBooking(text) {
  if (!/N[ÚU]MERO DE CONFIRMA[ÇC][ÃA]O/i.test(text)) return null;
  const ent = text.match(/ENTRADA\s*\n\s*(\d{1,2})\s*\n\s*([A-ZÇÃa-zçã]+)\s*\n\s*([A-Za-zçÇáéíóúÁÉÍÓÚ-]+)/);
  const sai = text.match(/SA[ÍI]DA\s*\n\s*(\d{1,2})\s*\n\s*([A-ZÇÃa-zçã]+)\s*\n\s*([A-Za-zçÇáéíóúÁÉÍÓÚ-]+)/);
  if (!ent || !sai) return null;

  const conf = text.match(/N[ÚU]MERO DE CONFIRMA[ÇC][ÃA]O\s*\n\s*([A-Z0-9][A-Z0-9.\- ]{3,20}?)\s*\n/i);
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  const hotel = lines[0];

  const mIn = MESES_PT[semAcento(ent[2])];
  const mOut = MESES_PT[semAcento(sai[2])];
  if (!mIn || !mOut) return null;
  const wIn = DIAS_SEMANA[semAcento(ent[3]).split('-')[0]];
  const wOut = DIAS_SEMANA[semAcento(sai[3]).split('-')[0]];
  const yIn = inferYear(Number(ent[1]), mIn, wIn);
  if (!yIn) return null;
  let yOut = yIn + (mOut < mIn ? 1 : 0);
  // confere pelo dia da semana; se não bater, tenta o ano seguinte
  const okDia = (y, d, m, w) => w === undefined || new Date(y, m - 1, d).getDay() === w;
  if (!okDia(yOut, Number(sai[1]), mOut, wOut) && okDia(yOut + 1, Number(sai[1]), mOut, wOut)) yOut += 1;
  const pad = (n) => String(n).padStart(2, '0');

  // Cidade: no "Endereço: rua, região, CEP Cidade, País" (o país pode quebrar de linha)
  let cidade = null;
  const end = text.match(/Endere[çc]o:\s*([\s\S]*?)\n\s*Telefone/i);
  if (end) {
    const partes = end[1].replace(/\s*\n\s*/g, ' ').split(',').map((p) => p.trim()).filter(Boolean);
    if (partes.length >= 2) {
      cidade = partes[partes.length - 2].replace(/^[\d][\d\s.-]*\s+/, '').replace(/^[A-Z]{1,2}\d[A-Z\d]*\s+\d[A-Z]{2}\s+/, '').trim();
    }
  }

  const hospede = text.match(/Nome do h[óo]spede:\s*([^\n]+)/i);
  const passageiros = hospede ? [hospede[1].trim()] : [];

  const avisos = ['Reserva de HOTEL: entrada = data ida, saída = data volta. Confira o ano e a cidade.'];
  return {
    tipo: 'hotel',
    data_ida: `${pad(ent[1])}/${pad(mIn)}/${yIn}`,
    horario_ida: null,
    itinerario_ida: cidade,
    data_volta: `${pad(sai[1])}/${pad(mOut)}/${yOut}`,
    horario_volta: null,
    itinerario_volta: null,
    cia_aerea: hotel || null,
    localizador: conf ? conf[1].trim() : null,
    passageiros,
    trechos_ida: [],
    trechos_volta: [],
    avisos
  };
}

// ---------------------------------------------------------------------------

function parseFlightText(rawText) {
  const text = String(rawText || '').replace(/\r/g, '').replace(/ /g, ' ');
  return parseEticketAgencia(text) || parseItinerarioReserva(text) || parseHotelBooking(text) || parseVisualizarReserva(text) || null;
}

module.exports = { parseFlightText };
