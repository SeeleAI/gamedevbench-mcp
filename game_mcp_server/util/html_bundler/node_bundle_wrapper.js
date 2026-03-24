/**
 * Node.js 包装器脚本
 * 从 Python 接收参数，调用 bundleFilesFromLocal 函数，返回 JSON 结果
 */
import { bundleFilesFromLocal } from './api/bundle.js';

// 从命令行参数获取 JSON 参数
const args = process.argv.slice(2);
if (args.length === 0) {
  console.error(JSON.stringify({
    success: false,
    message: 'No arguments provided'
  }));
  process.exit(1);
}

try {
  const params = JSON.parse(args[0]);
  const { srcDir, canvas_id, bucket, version } = params;
  
  if (!srcDir || !canvas_id || !bucket) {
    console.error(JSON.stringify({
      success: false,
      message: 'srcDir, canvas_id, and bucket are required'
    }));
    process.exit(1);
  }
  
  // 调用打包函数（version 是可选的）
  bundleFilesFromLocal(srcDir, canvas_id, bucket, version)
    .then(result => {
      // 输出 JSON 结果到 stdout
      console.log(JSON.stringify(result));
      process.exit(result.success ? 0 : 1);
    })
    .catch(error => {
      console.error(JSON.stringify({
        success: false,
        message: error.message || 'Unknown error',
        error: {
          type: 'NODE_ERROR',
          details: error.stack
        }
      }));
      process.exit(1);
    });
} catch (error) {
  console.error(JSON.stringify({
    success: false,
    message: `Failed to parse arguments: ${error.message}`
  }));
  process.exit(1);
}



