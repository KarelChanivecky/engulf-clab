const fs = require('fs');

function clientCertificates(path = process.env.ECLAB_PKI_PLAYWRIGHT_CLIENT_CERTIFICATES) {
  if (!path) return [];
  return JSON.parse(fs.readFileSync(path, 'utf8')).map(({ origin, certPath, keyPath }) => ({
    origin,
    cert: fs.readFileSync(certPath),
    key: fs.readFileSync(keyPath),
  }));
}

module.exports = { clientCertificates };
