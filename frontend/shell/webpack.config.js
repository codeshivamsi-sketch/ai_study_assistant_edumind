const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const { container } = require("webpack");
const { BundleAnalyzerPlugin } = require("webpack-bundle-analyzer");
const pkg = require("./package.json");

module.exports = (_env, argv) => {
  const isProd = argv.mode === "production";
  return {
    entry: "./src/index.tsx",
    mode: isProd ? "production" : "development",
    devtool: isProd ? "source-map" : "eval-source-map",
    output: {
      path: path.resolve(__dirname, "dist"),
      // Absolute, not "auto" — shell is the top-level page users deep-link
      // directly into (e.g. /documents/<uuid>). "auto" resolves the HTML's
      // own <script src> relative to the current URL path, which breaks on
      // any nested route (it'd request /documents/main.js instead of
      // /main.js). Remotes keep "auto" — they're script-injected
      // cross-origin and need it to resolve relative to their own origin.
      publicPath: "/",
      clean: true,
    },
    resolve: { extensions: [".ts", ".tsx", ".js"] },
    module: {
      rules: [
        { test: /\.tsx?$/, exclude: /node_modules/, use: "babel-loader" },
        // global.css only — the one global reset in the whole system
        { test: /\.css$/, exclude: /\.module\.css$/, use: ["style-loader", "css-loader"] },
        {
          test: /\.module\.css$/,
          use: [
            "style-loader",
            {
              loader: "css-loader",
              options: {
                modules: {
                  namedExport: false, // keep `import styles from "*.module.css"` as a default export
                  localIdentName: "shell__[name]__[local]__[hash:base64:5]",
                },
              },
            },
          ],
        },
      ],
    },
    devServer: {
      port: 3101,
      historyApiFallback: true,
      static: { directory: path.resolve(__dirname, "public") },
    },
    plugins: [
      new HtmlWebpackPlugin({ template: "./public/index.html" }),
      // No `exposes` — this ModuleFederationPlugin exists only to generate
      // the sharing runtime (__webpack_init_sharing__/__webpack_share_scopes__)
      // and hold the shared-singleton config for whatever shell's own bundle
      // and any dynamically-loaded remotes need to agree on.
      new container.ModuleFederationPlugin({
        name: "shell",
        shared: {
          react: { singleton: true, requiredVersion: pkg.dependencies.react },
          "react-dom": { singleton: true, requiredVersion: pkg.dependencies["react-dom"] },
          "react-router-dom": { singleton: true, requiredVersion: pkg.dependencies["react-router-dom"] },
        },
      }),
      ...(process.env.ANALYZE === "true"
        ? [new BundleAnalyzerPlugin({ analyzerMode: "static", reportFilename: "report.html", openAnalyzer: false })]
        : []),
    ],
  };
};
