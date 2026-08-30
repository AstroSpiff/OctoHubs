import { CheckCircle2, PlusCircle, XCircle } from "@/components/ui/icons";

import {
  formatLatestVerificationValue,
  type LatestVerificationCollection,
  type LatestVerificationField,
  type LatestVerificationFile,
} from "@/features/emby-latest/latest-data-availability";

function LatestVerificationFieldList({
  title,
  fields,
  tone,
}: {
  title: string;
  fields: LatestVerificationField[];
  tone: "available" | "missing" | "added";
}) {
  const Icon =
    tone === "available"
      ? CheckCircle2
      : tone === "added"
        ? PlusCircle
        : XCircle;
  const emptyLabel =
    tone === "missing" ? "Nessun dato mancante" : "Nessun dato";

  return (
    <section className={`latest-verification-section is-${tone}`}>
      <header>
        <h3>{title}</h3>
        <span>{fields.length}</span>
      </header>
      {fields.length ? (
        <dl className="latest-verification-fields">
          {fields.map((field) => (
            <div key={field.field}>
              <dt>
                <Icon size={13} aria-hidden="true" />
                <span>{field.label}</span>
                <small>{field.source}</small>
              </dt>
              <dd>{formatLatestVerificationValue(field.field, field.value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>{emptyLabel}</p>
      )}
    </section>
  );
}

function LatestVerificationCommon({
  verification,
}: {
  verification: LatestVerificationCollection;
}) {
  return (
    <section className="latest-verification-common">
      <header>
        <div>
          <h2>Informazioni comuni</h2>
          <p>Metadati, fonti esterne e dati disponibili per la pubblicazione.</p>
        </div>
        <span>
          {verification.available.length} disponibili · {verification.missing.length} mancanti
        </span>
      </header>
      <div className="latest-verification-columns">
        <LatestVerificationFieldList
          title="Disponibili"
          fields={verification.available}
          tone="available"
        />
        <LatestVerificationFieldList
          title="Mancanti"
          fields={verification.missing}
          tone="missing"
        />
      </div>
      {verification.added.length ? (
        <LatestVerificationFieldList
          title="Dati appena aggiunti"
          fields={verification.added}
          tone="added"
        />
      ) : null}
    </section>
  );
}

function LatestVerificationFiles({ files }: { files: LatestVerificationFile[] }) {
  return (
    <section className="latest-verification-files">
      <header>
        <h2>File e versioni</h2>
        <span>{files.length}</span>
      </header>
      {files.length ? (
        files.map((file) => (
          <article className="latest-verification-file" key={file.label}>
            <header>
              <h3>{file.label}</h3>
              <span>
                {file.available.length} disponibili · {file.missing.length} mancanti
              </span>
            </header>
            <div className="latest-verification-columns">
              <LatestVerificationFieldList
                title="Disponibili"
                fields={file.available}
                tone="available"
              />
              <LatestVerificationFieldList
                title="Mancanti"
                fields={file.missing}
                tone="missing"
              />
            </div>
          </article>
        ))
      ) : (
        <p>Nessun file rilevato per questa pubblicazione.</p>
      )}
    </section>
  );
}

export {
  LatestVerificationCommon,
  LatestVerificationFiles,
};
