// Mesmo formato aceito pelo SoapV1 (backend/soap/schema.py): letra + 2 dígitos e
// subcategoria opcional, com ou sem ponto ("g442" -> "G44.2"). Fora disso, null.
const CID10 = /^([A-Z])(\d{2})\.?(\d{1,2})?$/;

export function normalizarCid10(valor: string): string | null {
  const casamento = CID10.exec(valor.trim().toUpperCase());
  if (!casamento) return null;
  const [, letra, categoria, sub] = casamento;
  return `${letra}${categoria}${sub ? `.${sub}` : ""}`;
}
