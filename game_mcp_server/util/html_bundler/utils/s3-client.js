/**
 * S3 Client utility for html-bundler (simplified version)
 * Only upload functionality is needed since files are already downloaded in Python
 */
import { execFile } from 'child_process';
import { promisify } from 'util';
import { fileURLToPath } from 'url';
import path from 'path';

const execFileAsync = promisify(execFile);

// Get Python script path
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PYTHON_SCRIPT = path.join(__dirname, 's3_helper.py');

// Cache for Python command
let pythonCommand = null;

/**
 * Detect available Python command (python3 or python)
 */
async function detectPythonCommand() {
  if (pythonCommand) {
    return pythonCommand;
  }
  
  // Try python3 first (Linux/Mac)
  try {
    await execFileAsync('python3', ['--version'], { timeout: 5000 });
    pythonCommand = 'python3';
    return pythonCommand;
  } catch (error) {
    // Try python (Windows)
    try {
      await execFileAsync('python', ['--version'], { timeout: 5000 });
      pythonCommand = 'python';
      return pythonCommand;
    } catch (error2) {
      // Default to python3, will fail with clear error message
      pythonCommand = 'python3';
      return pythonCommand;
    }
  }
}

/**
 * Execute Python S3 helper script
 */
async function execPythonScript(command, args) {
  try {
    const pythonCmd = await detectPythonCommand();
    const s3OperationTimeout = 60000; // 60 seconds
    
    // 显式传递环境变量（确保 S3 凭证能够传递到 Python 子进程）
    const env = {
      ...process.env,  // 继承当前进程的所有环境变量
      // 确保这些关键环境变量存在
      S3_PRIVATE_ACCESS_KEY_ID: process.env.S3_PRIVATE_ACCESS_KEY_ID || '',
      S3_PRIVATE_SECRET_ACCESS_KEY: process.env.S3_PRIVATE_SECRET_ACCESS_KEY || '',
      S3_PRIVATE_REGION: process.env.S3_PRIVATE_REGION || 'ap-southeast-1',
    };
    
    const { stdout, stderr } = await execFileAsync(
      pythonCmd,
      [PYTHON_SCRIPT, command, ...args],
      {
        timeout: s3OperationTimeout,
        maxBuffer: 10 * 1024 * 1024, // 10MB buffer
        env: env,  // 显式传递环境变量
      }
    );
    
    // 记录 stderr（可能包含调试信息）
    if (stderr) {
      console.warn(`[S3 Helper] Python stderr: ${stderr}`);
    }
    
    // Parse JSON output
    let result;
    try {
      result = JSON.parse(stdout.trim());
    } catch (parseError) {
      console.error(`[S3 Helper] Failed to parse JSON output: ${stdout.substring(0, 500)}`);
      return {
        success: false,
        error: `Failed to parse Python script output: ${parseError.message}`
      };
    }
    
    // 如果结果失败，记录详细错误信息
    if (!result.success && result.error) {
      console.error(`[S3 Helper] Upload failed: ${result.error}`);
      if (result.error_details) {
        console.error(`[S3 Helper] Error details: ${JSON.stringify(result.error_details, null, 2)}`);
      }
    }
    
    return result;
  } catch (error) {
    // 重要：即使 Python 脚本返回非零退出码，也要先尝试解析 stdout 中的 JSON
    if (error.stdout) {
      try {
        const parsedResult = JSON.parse(error.stdout.trim());
        // 如果成功解析，返回解析结果（包含详细错误信息）
        if (!parsedResult.success && parsedResult.error) {
          console.error(`[S3 Helper] Python script returned error: ${parsedResult.error}`);
          if (parsedResult.error_details) {
            console.error(`[S3 Helper] Error details: ${JSON.stringify(parsedResult.error_details, null, 2)}`);
          }
        }
        return parsedResult;
      } catch (parseError) {
        // JSON 解析失败，继续使用异常信息
        console.warn(`[S3 Helper] Failed to parse stdout as JSON: ${parseError.message}`);
      }
    }
    
    const errorDetails = {
      message: error.message || 'Unknown error',
      code: error.code || null,
      signal: error.signal || null,
      stdout: error.stdout ? error.stdout.substring(0, 2000) : null,
      stderr: error.stderr ? error.stderr.substring(0, 2000) : null,
    };
    
    console.error(`[S3 Helper] Error executing Python script:`, error);
    console.error(`[S3 Helper] Error details:`, JSON.stringify(errorDetails, null, 2));
    
    // 构建详细的错误消息
    let errorMessage = error.message || 'Unknown error executing Python script';
    if (error.code) {
      errorMessage += ` (code: ${error.code})`;
    }
    if (error.stdout) {
      errorMessage += ` | stdout: ${error.stdout.substring(0, 500)}`;
    }
    if (error.stderr) {
      errorMessage += ` | stderr: ${error.stderr.substring(0, 500)}`;
    }
    
    return {
      success: false,
      error: errorMessage,
      error_details: errorDetails
    };
  }
}

/**
 * 直接上传文件到 S3 URL（带重试机制）
 * 
 * 注意：此函数已废弃，不再被使用。
 * 当前流程使用文件路径上传（通过 Python s3_helper.py），避免内存占用。
 * 
 * @param {string} s3Url - 完整的 S3 URL (格式: s3://bucket/key)
 * @param {string} content - 文件内容（内存内容，已废弃）
 * @param {string} contentType - 内容类型（可选，默认 'text/html'）
 * @param {number} maxRetries - 最大重试次数（默认3次）
 * @returns {Promise<{success: boolean, error?: string}>}
 * @deprecated 此函数已废弃，当前代码不再使用内存内容上传
 */
export async function uploadFileToUrl(s3Url, content, contentType = 'text/html', maxRetries = 3) {
  // 验证 S3 URL 格式
  if (!s3Url.startsWith('s3://')) {
    return {
      success: false,
      error: `Invalid S3 URL format: ${s3Url}. Must start with 's3://'`
    };
  }
  
  const fs = await import('fs/promises');
  const os = await import('os');
  const { randomUUID } = await import('crypto');
  
  // 从 URL 提取文件名用于临时文件
  const urlParts = s3Url.split('/');
  const fileName = urlParts[urlParts.length - 1] || 'file';
  const tempDir = os.tmpdir();
  const tempFile = path.join(tempDir, `html-bundler-${randomUUID()}-${fileName}`);
  
  let lastError = null;
  
  try {
    // Write content to temp file
    await fs.writeFile(tempFile, content, 'utf-8');
    
    // 重试逻辑
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        if (attempt > 0) {
          // 指数退避：1s, 2s, 4s
          const delay = Math.pow(2, attempt - 1) * 1000;
          await new Promise(resolve => setTimeout(resolve, delay));
        }
        
        // Upload via Python script
        const result = await execPythonScript('upload', [
          '--local-path', tempFile,
          '--s3-url', s3Url,
          '--content-type', contentType,
        ]);
        
        if (!result.success) {
          lastError = result.error || 'Upload failed';
          if (attempt < maxRetries) {
            continue; // 重试
          }
          return {
            success: false,
            error: lastError
          };
        }
        
        // 成功
        return { success: true };
      } catch (error) {
        lastError = error.message;
        if (attempt < maxRetries) {
          continue; // 重试
        }
        return {
          success: false,
          error: lastError
        };
      }
    }
    
    // 所有重试都失败
    return {
      success: false,
      error: lastError || 'Upload failed after retries'
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  } finally {
    // Clean up temp file
    try {
      await fs.unlink(tempFile);
    } catch (cleanupError) {
      // 忽略清理错误
    }
  }
}



