import SwaggerUI from "swagger-ui-dist/swagger-ui-es-bundle.js";
import "swagger-ui-dist/swagger-ui.css";

SwaggerUI({
  dom_id: "#swagger-ui",
  url: "/openapi.json",
  deepLinking: true,
  displayOperationId: true,
  displayRequestDuration: true,
  filter: true,
  docExpansion: "none",
  persistAuthorization: false,
  supportedSubmitMethods: [],
  validatorUrl: "",
});
