type AlternativeTitleLanguageFieldProps = {
  checked: boolean;
  disabled?: boolean;
  includeAllLanguages?: boolean;
  label: string;
  language: string;
  onCheckedChange: (checked: boolean) => void;
  onLanguageChange: (language: string) => void;
};

const languageOptions = ["it", "en", "es", "fr", "de", "pt", "ru", "ja", "ko", "zh", "ar"];

function AlternativeTitleLanguageField({
  checked,
  disabled = false,
  includeAllLanguages = false,
  label,
  language,
  onCheckedChange,
  onLanguageChange,
}: AlternativeTitleLanguageFieldProps) {
  return (
    <div className="research-toggle research-toggle--language">
      <label className="research-toggle-choice">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onCheckedChange(event.target.checked)}
        />
        <span>{label}</span>
      </label>
      <label className="research-language-choice">
        <span className="sr-only">Lingua titoli alternativi</span>
        <select
          aria-label="Lingua titoli alternativi"
          value={language}
          disabled={disabled || !checked}
          onChange={(event) => onLanguageChange(event.target.value)}
        >
          {includeAllLanguages ? <option value="all">Tutte</option> : null}
          {languageOptions.map((option) => (
            <option key={option} value={option}>{option.toUpperCase()}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

export { AlternativeTitleLanguageField };
