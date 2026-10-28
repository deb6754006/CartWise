// Needed by the jest-expo/android preset, which reads the project's Babel config.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
  };
};
