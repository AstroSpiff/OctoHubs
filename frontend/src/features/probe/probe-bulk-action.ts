type ProbeBulkActionNotice = {
  message: string;
  tone: "success" | "warning";
};

function probeBulkActionNotice(
  label: string,
  succeeded: number,
  total: number,
): ProbeBulkActionNotice {
  if (!total) {
    return {
      message: `Nessun server disponibile per svuotare ${label.toLocaleLowerCase("it")}.`,
      tone: "warning",
    };
  }
  if (succeeded === total) {
    return {
      message: `Svuotamento ${label.toLocaleLowerCase("it")} completato su ${total} server.`,
      tone: "success",
    };
  }
  return {
    message: `Svuotamento ${label.toLocaleLowerCase("it")} completato su ${succeeded} di ${total} server. Controlla gli errori segnalati.`,
    tone: "warning",
  };
}

export { probeBulkActionNotice };
