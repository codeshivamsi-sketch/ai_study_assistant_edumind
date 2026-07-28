const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const { container } = require("webpack");
const { BundleAnalyzerPlugin } = require("webpack-bundle-analyzer");
const pkg = require("./package.json");

module.exports = (_env, argv) => {
  const isProd = argv.mode === "production";
  return {
    entry: "./src/index.tsx", // dev-harness only; ChatApp.tsx is the real federation contract
    mode: isProd ? "production" : "development",
    devtool: isProd ? "source-map" : "eval-source-map",
    output: { path: path.resolve(__dirname, "dist"), publicPath: "auto", clean: true },
    resolve: { extensions: [".ts", ".tsx", ".js"] },
    module: {
      rules: [
        { test: /\.tsx?$/, exclude: /node_modules/, use: "babel-loader" },
        {
          test: /\.module\.css$/,
          use: [
            "style-loader",
            {
              loader: "css-loader",
              options: {
                modules: {
                  namedExport: false, // keep `import styles from "*.module.css"` as a default export
                  localIdentName: "chat__[name]__[local]__[hash:base64:5]",
                },
              },
            },
          ],
        },
      ],
    },
    devServer: {
      port: 3104,
      historyApiFallback: true,
      static: { directory: path.resolve(__dirname, "public") },
      // webpack-dev-server 5.x defaults to Cross-Origin-Resource-Policy:
      // same-origin, which blocks other apps' <script src> load of
      // remoteEntry.js across origins/ports.
      headers: { "Cross-Origin-Resource-Policy": "cross-origin" },
    },
    plugins: [
      new HtmlWebpackPlugin({ template: "./public/index.html" }),
      new container.ModuleFederationPlugin({
        name: "chat",
        filename: "remoteEntry.js",
        exposes: { "./ChatApp": "./src/ChatApp" },
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
