declare module 'plotly.js-dist-min' {
  const Plotly: {
    newPlot(root: HTMLElement, data: unknown[], layout?: object, config?: object): Promise<unknown>;
  };
  export default Plotly;
}
