/**
 * Bundle API endpoint
 * Bundles files from local directory into a single index.html
 * Modified version that accepts local files instead of downloading from S3
 */
import { exec } from 'child_process';
import { promisify } from 'util';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { config } from '../config/config.js';
// createHash 已不再使用（移除了 hash 路径计算，避免读取文件到内存）

const execAsync = promisify(exec);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// PROJECT_ROOT 指向 html_bundler 目录（包含 node_modules）
const PROJECT_ROOT = path.resolve(__dirname, '..');

/**
 * Bundle files from local directory
 * @param {string} srcDir - Local source directory containing files to bundle
 * @param {string} canvas_id - 画布 ID（用于构建临时目录路径）
 * @param {string} bucket - S3 bucket name
 * @param {number|null} version - 版本号（可选），如果提供则使用版本路径（publish 场景），否则不计算路径（read_console 场景）
 */
export async function bundleFilesFromLocal(srcDir, canvas_id, bucket, version = null) {
  const startTime = Date.now();
  const bundleId = Math.random().toString(36).substring(2, 10);
  
  // 在日志中包含 canvas_id，方便按画布查询日志
  const logPrefix = `[Bundle] [${bundleId}] [canvas:${canvas_id}]`;
  console.log(`${logPrefix} Starting bundle from local directory: ${srcDir}`);
  
  try {
    // 1. 验证源目录存在
    try {
      await fs.access(srcDir);
    } catch (error) {
      console.error(`${logPrefix} ERROR: Source directory does not exist: ${srcDir}`);
      return {
        success: false,
        message: `Failed to bundle files: Source directory does not exist`,
        error_type: 'invalid_directory',
      };
    }
    
    // 2. 列出所有文件（递归）
    const files = [];
    async function listFilesRecursive(dir, baseDir = dir) {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        const relativePath = path.relative(baseDir, fullPath).replace(/\\/g, '/');
        
        if (entry.isDirectory()) {
          await listFilesRecursive(fullPath, baseDir);
        } else {
          files.push(relativePath);
        }
      }
    }
    
    await listFilesRecursive(srcDir);
    
    if (files.length === 0) {
      console.error(`${logPrefix} ERROR: No files found in source directory`);
      return {
        success: false,
        message: 'Failed to bundle files: No files found in source directory',
        error_type: 'no_files',
      };
    }
    
    console.log(`${logPrefix} Found ${files.length} files to bundle`);
    
    // 3. 验证 canvas_id 参数
    if (!canvas_id) {
      console.error(`${logPrefix} ERROR: canvas_id is required`);
      return {
        success: false,
        message: 'Failed to bundle files: canvas_id is required',
        error_type: 'missing_canvas_id',
      };
    }
    
    // 4. 构建上传路径（根据是否有版本号决定）
    // 注意：tempPrefix 和 tempUploadUrl 变量已不再使用（上传在 Python 端完成）
    // 但保留版本路径的日志记录，用于调试
    if (version !== null && version !== undefined) {
      // 版本打包：使用版本路径
      console.log(`${logPrefix} Using version path: V${version}`);
    } else {
      // 非版本打包：read_console 场景，不需要上传，不需要计算 hash
      console.log(`${logPrefix} Non-version bundle (read_console scenario, no S3 upload needed)`);
    }
    
    // 5. Execute vite build
    const tempViteConfigPath = path.join(srcDir, 'vite.config.temp.js');
    const relativePathToProjectRoot = path.relative(srcDir, PROJECT_ROOT).replace(/\\/g, '/');
    const nodeModulesPath = relativePathToProjectRoot ? `${relativePathToProjectRoot}/node_modules` : '../node_modules';
    
    const viteConfigContent = `
import { defineConfig } from '${nodeModulesPath}/vite';
import { viteSingleFile } from '${nodeModulesPath}/vite-plugin-singlefile';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  root: __dirname,
  build: {
    outDir: path.join(__dirname, 'dist'),
    assetsDir: '',
    minify: false,
    cssMinify: false,
    rollupOptions: {
      input: path.join(__dirname, 'index.html'),
      external: [
        'three',
        /^three\\/addons\\/.*/,
        'cannon-es',
        'ThreeSeeleAdSdk',
        'GameEventAnalys',
        'IncentiveSDK',
        'ThreeGameAdSDK',
        'SpriteAnimation',
        // skill 组件（templates 目录）：不打包，运行时按需加载
        /[\\/]templates[\\/].*\\.(js|mjs|ts)$/,
      ],
      output: {
        inlineDynamicImports: true,
      },
    },
    optimizeDeps: {
      exclude: ['three'],
    },
  },
  plugins: [
    viteSingleFile({
      removeViteModuleLoader: true,
    }),
  ],
});
`;
    
    await fs.writeFile(tempViteConfigPath, viteConfigContent, 'utf-8');
    
    // Build using vite from project root (with retry mechanism)
    const maxBuildRetries = 3;
    let buildSuccess = false;
    let lastBuildError = null;
    
    for (let attempt = 0; attempt <= maxBuildRetries; attempt++) {
      try {
        if (attempt > 0) {
          // 指数退避：3s, 6s, 12s（增加退避时间，给系统更多恢复时间）
          const delay = 3 * Math.pow(2, attempt - 1) * 1000;
          await new Promise(resolve => setTimeout(resolve, delay));
          console.log(`${logPrefix} Retrying Vite build (attempt ${attempt + 1}/${maxBuildRetries + 1})`);
        }
        
        // 用 node 直接跑 vite.js，避免依赖 .bin/vite（.cmd），在 temp 在 C:、项目在 D: 等跨盘符时更稳
        const viteJsPath = path.join(PROJECT_ROOT, 'node_modules', 'vite', 'bin', 'vite.js');
        const nodePath = process.env.NODE_PATH ? `${PROJECT_ROOT}${path.delimiter}${process.env.NODE_PATH}` : PROJECT_ROOT;
        
        // 确保超时时间至少为 20 秒
        const buildTimeout = Math.max(20000, config.bundle.timeout - 20000);
        
        // 使用 srcDir 作为 cwd，确保路径一致性
        // Vite 配置中的 root 是 __dirname（指向 srcDir），所以 cwd 也应该指向 srcDir
        const { stdout: buildStdout, stderr: buildStderr } = await execAsync(
          `node "${viteJsPath}" build --config "${tempViteConfigPath}"`,
          { 
            cwd: srcDir,  // 改为 srcDir，与 Vite 配置的 root 保持一致
            timeout: buildTimeout,
            env: { 
              ...process.env, 
              NODE_ENV: 'production',
              NODE_PATH: nodePath
            }
          }
        );
        
        // 检查构建输出中是否包含错误
        const errorPatterns = [/error:/i, /failed/i, /cannot/i, /not found/i, /syntax error/i];
        const hasError = errorPatterns.some(pattern => 
          pattern.test(buildStdout) || (buildStderr && pattern.test(buildStderr))
        );
        
        if (hasError) {
          lastBuildError = `Vite build output contains errors. Stdout: ${buildStdout.substring(0, 200)}...`;
          
          // 检测资源错误（不应该重试）
          // 注意：这些错误可能出现在 Vite 构建的 stdout/stderr 中
          const isResourceError = 
            /cannot fork/i.test(buildStdout) ||
            /cannot fork/i.test(buildStderr || '') ||
            /resource temporarily unavailable/i.test(buildStdout) ||
            /resource temporarily unavailable/i.test(buildStderr || '') ||
            /errno\s*11/i.test(buildStdout) ||
            /errno\s*11/i.test(buildStderr || '') ||
            /uv_thread_create/i.test(buildStdout) ||
            /uv_thread_create/i.test(buildStderr || '');
          
          if (isResourceError) {
            // 资源错误立即失败，不重试（避免加剧资源竞争）
            console.error(`${logPrefix} ERROR: Resource error detected, not retrying: ${lastBuildError}`);
            return {
              success: false,
              message: `Failed to bundle files: System resource exhausted - ${lastBuildError}`,
              error_type: 'resource_exhausted',
            };
          }
          
          // 其他错误可以重试
          if (attempt < maxBuildRetries) {
            continue; // 重试
          }
          console.error(`${logPrefix} ERROR: Vite build output contains errors`);
          console.error(`${logPrefix} Build stdout: ${buildStdout.substring(0, 500)}`);
          if (buildStderr) {
            console.error(`${logPrefix} Build stderr: ${buildStderr.substring(0, 500)}`);
          }
          return {
            success: false,
            message: `Failed to bundle files: Build failed${lastBuildError ? ` - ${lastBuildError}` : ''}`,
            error_type: 'build_failed',
          };
        }
        
        // 构建成功
        buildSuccess = true;
        break;
      } catch (buildError) {
        lastBuildError = buildError.message;
        
        // 检测资源错误（不应该重试）
        // 注意：这些错误可能出现在 Vite 构建的 stdout/stderr 中
        const errorMessage = buildError.message || '';
        const errorStderr = buildError.stderr || '';
        const errorStdout = buildError.stdout || '';
        const isResourceError = 
          /cannot fork/i.test(errorMessage) ||
          /cannot fork/i.test(errorStderr) ||
          /cannot fork/i.test(errorStdout) ||
          /resource temporarily unavailable/i.test(errorMessage) ||
          /resource temporarily unavailable/i.test(errorStderr) ||
          /resource temporarily unavailable/i.test(errorStdout) ||
          /errno\s*11/i.test(errorMessage) ||
          /errno\s*11/i.test(errorStderr) ||
          /errno\s*11/i.test(errorStdout) ||
          /uv_thread_create/i.test(errorMessage) ||
          /uv_thread_create/i.test(errorStderr) ||
          /uv_thread_create/i.test(errorStdout);
        
        if (isResourceError) {
          // 资源错误立即失败，不重试（避免加剧资源竞争）
          console.error(`${logPrefix} ERROR: Resource error detected, not retrying: ${lastBuildError}`);
          return {
            success: false,
            message: `Failed to bundle files: System resource exhausted - ${lastBuildError}`,
            error_type: 'resource_exhausted',
          };
        }
        
        // 其他错误可以重试
        if (attempt < maxBuildRetries) {
          console.warn(`${logPrefix} Vite build attempt ${attempt + 1} failed: ${buildError.message}, retrying...`);
          continue; // 重试
        }
        console.error(`${logPrefix} ERROR: Vite build failed after ${maxBuildRetries + 1} attempts: ${lastBuildError}`);
        return {
          success: false,
          message: `Failed to bundle files: Build failed - ${lastBuildError}`,
          error_type: 'build_failed',
        };
      }
    }
    
    // 理论上不应该到达这里（因为成功会 break，失败会 return），但作为安全网保留
    if (!buildSuccess) {
      return {
        success: false,
        message: `Failed to bundle files: Build failed${lastBuildError ? ` - ${lastBuildError}` : ''}`,
        error_type: 'build_failed',
      };
    }
    
    // 6. 验证打包后的 index.html 文件存在（不读取内容，避免内存占用）
    // 根据 Vite 配置：root = srcDir, outDir = srcDir/dist，输出应该是 srcDir/dist/index.html
    const bundledHtmlPath = path.join(srcDir, 'dist', 'index.html');
    let relativeHtmlPath;
    let htmlFileSize;
    
    try {
      // 使用 fs.stat 检查文件存在并获取文件大小（不读取内容）
      const stats = await fs.stat(bundledHtmlPath);
      relativeHtmlPath = path.relative(srcDir, bundledHtmlPath).replace(/\\/g, '/');
      console.log(`${logPrefix} Found bundled HTML at: ${relativeHtmlPath}`);
      
      // 验证文件大小（文件不能为空）
      if (stats.size === 0) {
        console.error(`${logPrefix} ERROR: Bundled HTML file is empty`);
        return {
          success: false,
          message: 'Failed to bundle files: Bundled file is empty',
          error_type: 'build_failed',
        };
      }
      
      // 获取文件大小（不读取内容）
      htmlFileSize = stats.size;
      
      // 7. 返回文件路径而不是 HTML 内容（避免通过 stdout 传输大型数据）
      // HTML 文件已经存在于 dist/index.html，Python 端会直接从文件读取
      const totalDuration = Date.now() - startTime;
      
      console.log(`${logPrefix} Bundle complete (${totalDuration}ms, ${htmlFileSize}b)`);
      
    } catch (error) {
      console.error(`${logPrefix} ERROR: Bundled file not found at: ${path.relative(srcDir, bundledHtmlPath).replace(/\\/g, '/')}`);
      console.error(`${logPrefix} Error details: ${error.message}`);
      return {
        success: false,
        message: `Failed to bundle files: Bundled file not found at dist/index.html`,
        error_type: 'build_failed',
      };
    }
    
    return {
      success: true,
      message: `Successfully bundled ${files.length} files into index.html`,
      data: {
        files_count: files.length,
        bundled_html_path: relativeHtmlPath,  // 只返回相对路径，不返回 HTML 内容
        bundled_html_size: htmlFileSize,      // 文件大小（用于验证）
        canvas_id: canvas_id,
        version: version,
        cached: false,
      },
    };
    
  } catch (error) {
    console.error(`${logPrefix} ERROR: ${error.message}`);
    return {
      success: false,
      message: 'Failed to bundle files: Unexpected error',
      error_type: 'unknown_error',
    };
  }
}



