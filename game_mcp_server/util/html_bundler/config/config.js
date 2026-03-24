/**
 * Configuration for html-bundler
 */
export const config = {
  // Server configuration
  server: {
    port: parseInt(process.env.PORT || '3000', 10),
  },
  
  // Bundle configuration
  bundle: {
    timeout: parseInt(process.env.BUNDLE_TIMEOUT || '90000', 10), // 90 seconds
    workDirBase: process.env.BUNDLE_WORK_DIR || '/tmp/html-bundler',
  },
};



