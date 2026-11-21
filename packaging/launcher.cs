using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

internal static class Program
{
    private const int FooterSize = 44;
    private const int HashSize = 32;

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            string exe = Process.GetCurrentProcess().MainModule.FileName;
            string home = Path.GetDirectoryName(exe);
            string hash = ReadHash(exe);
            string runtimeRoot = Environment.GetEnvironmentVariable("BABANONGCHANG_RUNTIME");
            if (string.IsNullOrEmpty(runtimeRoot))
            {
                runtimeRoot = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "babanongchang",
                    "runtime");
            }
            string target = Path.Combine(runtimeRoot, hash);
            string inner = Path.Combine(target, "babanongchang.exe");
            bool owned = false;
            Mutex mutex = new Mutex(false, "Local\\babanongchang-" + hash);
            try
            {
                try
                {
                    owned = mutex.WaitOne();
                }
                catch (AbandonedMutexException)
                {
                    owned = true;
                }
                if (!File.Exists(Path.Combine(target, "ready")) || !File.Exists(inner))
                {
                    Extract(exe, target, hash);
                }
            }
            finally
            {
                if (owned)
                {
                    mutex.ReleaseMutex();
                }
                mutex.Dispose();
            }
            RemoveOtherVersions(runtimeRoot, target);
            return Start(inner, home, args);
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "\u82ad\u82ad\u519c\u573a", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string ReadHash(string exe)
    {
        using (FileStream stream = OpenExe(exe))
        {
            byte[] footer = ReadFooter(stream);
            return ToHex(Hash(footer));
        }
    }

    private static void Extract(string exe, string target, string hash)
    {
        Exception error = null;
        Thread worker = new Thread(delegate()
        {
            try
            {
                ExtractPayload(exe, target, hash);
            }
            catch (Exception ex)
            {
                error = ex;
            }
        });
        worker.IsBackground = true;
        worker.Start();
        if (!worker.Join(400))
        {
            Form form = new Form();
            form.Text = "\u82ad\u82ad\u519c\u573a";
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.StartPosition = FormStartPosition.CenterScreen;
            form.MaximizeBox = false;
            form.MinimizeBox = false;
            form.ControlBox = false;
            form.TopMost = true;
            form.ClientSize = new System.Drawing.Size(420, 90);
            Label label = new Label();
            label.Text = "\u9996\u6b21\u542f\u52a8\u6b63\u5728\u51c6\u5907\u7a0b\u5e8f\uff0c\u8bf7\u7a0d\u5019\u2026";
            label.Dock = DockStyle.Fill;
            label.TextAlign = System.Drawing.ContentAlignment.MiddleCenter;
            form.Controls.Add(label);
            form.Show();
            Application.DoEvents();
            while (worker.IsAlive)
            {
                Application.DoEvents();
                Thread.Sleep(50);
            }
            form.Close();
        }
        if (error != null)
        {
            throw error;
        }
    }

    private static void ExtractPayload(string exe, string target, string hash)
    {
        string parent = Path.GetDirectoryName(target);
        Directory.CreateDirectory(parent);
        string staging = target + ".partial";
        if (Directory.Exists(staging))
        {
            Directory.Delete(staging, true);
        }
        Directory.CreateDirectory(staging);
        string tempZip = Path.Combine(Path.GetTempPath(), "babanongchang-" + hash + ".zip");
        try
        {
            using (FileStream stream = OpenExe(exe))
            {
                byte[] footer = ReadFooter(stream);
                byte[] expected = Hash(footer);
                long length = Length(footer);
                long offset = stream.Length - FooterSize - length;
                if (offset < 0 || ToHex(expected) != hash)
                {
                    throw new InvalidDataException("\u7a0b\u5e8f\u6587\u4ef6\u5df2\u635f\u574f\u3002");
                }
                stream.Seek(offset, SeekOrigin.Begin);
                using (FileStream output = File.Create(tempZip))
                using (SHA256 algorithm = SHA256.Create())
                {
                    byte[] buffer = new byte[1024 * 1024];
                    long remaining = length;
                    while (remaining > 0)
                    {
                        int count = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, remaining));
                        if (count == 0)
                        {
                            throw new EndOfStreamException("\u7a0b\u5e8f\u6587\u4ef6\u5df2\u635f\u574f\u3002");
                        }
                        algorithm.TransformBlock(buffer, 0, count, null, 0);
                        output.Write(buffer, 0, count);
                        remaining -= count;
                    }
                    algorithm.TransformFinalBlock(buffer, 0, 0);
                    if (!Same(algorithm.Hash, expected))
                    {
                        throw new InvalidDataException("\u7a0b\u5e8f\u6587\u4ef6\u5df2\u635f\u574f\u3002");
                    }
                }
            }
            using (FileStream zip = File.OpenRead(tempZip))
            using (ZipArchive archive = new ZipArchive(zip, ZipArchiveMode.Read))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    ExtractEntry(staging, entry);
                }
            }
            File.WriteAllText(Path.Combine(staging, "ready"), hash, Encoding.ASCII);
            if (Directory.Exists(target))
            {
                Directory.Delete(target, true);
            }
            Directory.Move(staging, target);
        }
        catch
        {
            if (Directory.Exists(staging))
            {
                Directory.Delete(staging, true);
            }
            throw;
        }
        finally
        {
            if (File.Exists(tempZip))
            {
                File.Delete(tempZip);
            }
        }
    }

    private static void ExtractEntry(string staging, ZipArchiveEntry entry)
    {
        string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
        if (relative.Length == 0)
        {
            return;
        }
        string destination = Path.GetFullPath(Path.Combine(staging, relative));
        string root = Path.GetFullPath(staging + Path.DirectorySeparatorChar);
        if (!destination.StartsWith(root, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("\u7a0b\u5e8f\u6587\u4ef6\u5df2\u635f\u574f\u3002");
        }
        if (relative[relative.Length - 1] == Path.DirectorySeparatorChar || entry.Name.Length == 0)
        {
            Directory.CreateDirectory(destination);
            return;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(destination));
        using (Stream input = entry.Open())
        using (FileStream output = File.Create(destination))
        {
            input.CopyTo(output);
        }
    }


    private static void RemoveOtherVersions(string runtimeRoot, string target)
    {
        if (!Directory.Exists(runtimeRoot))
        {
            return;
        }
        string current = Path.GetFullPath(target);
        foreach (string entry in Directory.GetDirectories(runtimeRoot))
        {
            if (string.Equals(Path.GetFullPath(entry), current, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            try
            {
                Directory.Delete(entry, true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
    private static int Start(string inner, string home, string[] args)
    {
        if (!File.Exists(inner))
        {
            throw new FileNotFoundException("\u627e\u4e0d\u5230\u4e3b\u7a0b\u5e8f\u3002", inner);
        }
        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = inner;
        info.WorkingDirectory = home;
        info.UseShellExecute = false;
        info.Arguments = QuoteAll(args);
        info.EnvironmentVariables["BABANONGCHANG_HOME"] = home;
        using (Process process = Process.Start(info))
        {
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    private static FileStream OpenExe(string exe)
    {
        return new FileStream(exe, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
    }

    private static byte[] ReadFooter(FileStream stream)
    {
        if (stream.Length < FooterSize)
        {
            throw new InvalidDataException("\u65e0\u6cd5\u8bfb\u53d6\u7a0b\u5e8f\u5185\u5bb9\u3002");
        }
        byte[] footer = new byte[FooterSize];
        stream.Seek(-FooterSize, SeekOrigin.End);
        int read = stream.Read(footer, 0, FooterSize);
        if (read != FooterSize || footer[40] != (byte)'B' || footer[41] != (byte)'B' || footer[42] != (byte)'N' || footer[43] != (byte)'C')
        {
            throw new InvalidDataException("\u65e0\u6cd5\u8bfb\u53d6\u7a0b\u5e8f\u5185\u5bb9\u3002");
        }
        return footer;
    }

    private static byte[] Hash(byte[] footer)
    {
        byte[] hash = new byte[HashSize];
        Buffer.BlockCopy(footer, 0, hash, 0, HashSize);
        return hash;
    }

    private static long Length(byte[] footer)
    {
        return BitConverter.ToInt64(footer, HashSize);
    }

    private static string ToHex(byte[] value)
    {
        StringBuilder builder = new StringBuilder(value.Length * 2);
        for (int index = 0; index < value.Length; index++)
        {
            builder.Append(value[index].ToString("x2"));
        }
        return builder.ToString();
    }

    private static bool Same(byte[] left, byte[] right)
    {
        if (left == null || right == null || left.Length != right.Length)
        {
            return false;
        }
        for (int index = 0; index < left.Length; index++)
        {
            if (left[index] != right[index])
            {
                return false;
            }
        }
        return true;
    }

    private static string QuoteAll(string[] args)
    {
        StringBuilder builder = new StringBuilder();
        for (int index = 0; index < args.Length; index++)
        {
            if (index > 0)
            {
                builder.Append(' ');
            }
            builder.Append(Quote(args[index]));
        }
        return builder.ToString();
    }

    private static string Quote(string value)
    {
        if (value.Length == 0)
        {
            return "\"\"";
        }
        if (value.IndexOf(' ') < 0 && value.IndexOf('\t') < 0 && value.IndexOf('"') < 0)
        {
            return value;
        }
        StringBuilder builder = new StringBuilder();
        builder.Append('"');
        int slashes = 0;
        for (int index = 0; index < value.Length; index++)
        {
            char ch = value[index];
            if (ch == '\\')
            {
                slashes++;
                continue;
            }
            if (ch == '"')
            {
                builder.Append('\\', slashes * 2 + 1);
                builder.Append('"');
                slashes = 0;
                continue;
            }
            if (slashes > 0)
            {
                builder.Append('\\', slashes);
                slashes = 0;
            }
            builder.Append(ch);
        }
        if (slashes > 0)
        {
            builder.Append('\\', slashes * 2);
        }
        builder.Append('"');
        return builder.ToString();
    }
}
