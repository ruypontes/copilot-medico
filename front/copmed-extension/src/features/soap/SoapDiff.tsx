import { useState } from "react";
import type { SoapDiffResult, SoapDiffSection, SoapDiffSnippet } from "../shared/types";

// Diferença entre o SOAP gerado pela IA e o editado pelo médico (B44 / US018).
// O diff vem pronto da API (GET /api/consultations/<id>/soap); aqui só a exibição,
// para o SoapEditor (B43) mostrar depois da edição.

function Trecho({ trecho }: { trecho: SoapDiffSnippet }) {
  if (trecho.op === "removido") {
    return (
      <del className="soap-diff-removido" title="Removido do texto da IA">
        {trecho.texto}
      </del>
    );
  }
  if (trecho.op === "adicionado") {
    return (
      <ins className="soap-diff-adicionado" title="Incluído pelo médico">
        {trecho.texto}
      </ins>
    );
  }
  return <span>{trecho.texto}</span>;
}

function Secao({ secao }: { secao: SoapDiffSection }) {
  const vazia = secao.trechos.length === 0;
  return (
    <section className="soap-diff-secao" aria-label={secao.titulo}>
      <h4 className="soap-diff-titulo">
        {secao.titulo}
        {secao.alterada && <span className="soap-diff-selo">alterada</span>}
      </h4>
      {vazia ? (
        <p className="soap-diff-vazio">—</p>
      ) : secao.tipo === "lista" ? (
        <ul className="soap-diff-lista">
          {secao.trechos.map((trecho, i) => (
            <li key={i} className={`soap-diff-item-${trecho.op}`}>
              {/* Prefixo além da cor: a diferença não depende só de cor */}
              <span aria-hidden="true">{trecho.op === "removido" ? "− " : trecho.op === "adicionado" ? "+ " : ""}</span>
              <Trecho trecho={trecho} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="soap-diff-texto">
          {secao.trechos.map((trecho, i) => (
            <Trecho key={i} trecho={trecho} />
          ))}
        </p>
      )}
    </section>
  );
}

export default function SoapDiff({ diff }: { diff: SoapDiffResult | null }) {
  const [mostrarTodas, setMostrarTodas] = useState(false);

  if (!diff) {
    return <p className="soap-diff-aviso">Sem edição do médico: o texto é o gerado pela IA.</p>;
  }
  if (!diff.alterado) {
    return <p className="soap-diff-aviso">O médico não alterou o texto gerado pela IA.</p>;
  }

  const total = diff.secoes_alteradas.length;
  const visiveis = mostrarTodas ? diff.secoes : diff.secoes.filter((s) => s.alterada);

  return (
    <div className="soap-diff">
      <p className="soap-diff-resumo">
        {total} {total === 1 ? "seção alterada" : "seções alteradas"} pelo médico.{" "}
        <span className="soap-diff-legenda">
          <del className="soap-diff-removido">Riscado</del>: saiu do texto da IA ·{" "}
          <ins className="soap-diff-adicionado">destacado</ins>: incluído pelo médico
        </span>
      </p>
      {visiveis.map((secao) => (
        <Secao key={secao.secao} secao={secao} />
      ))}
      {total < diff.secoes.length && (
        <button type="button" className="btn-white small" onClick={() => setMostrarTodas((v) => !v)}>
          {mostrarTodas ? "Mostrar só as alteradas" : "Mostrar todas as seções"}
        </button>
      )}
    </div>
  );
}
