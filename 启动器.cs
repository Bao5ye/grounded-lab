using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Diagnostics;
using System.Text;
using System.Threading;
using System.Collections.Generic;
using System.Web.Script.Serialization;

class GroundedLauncher {
 const int Port=48328, MaxBody=3*1024*1024;
 static readonly string Root=AppDomain.CurrentDomain.BaseDirectory;
 static JavaScriptSerializer Json(){return new JavaScriptSerializer { MaxJsonLength=6*1024*1024, RecursionLimit=100 };}
 static void Main(string[] args) {
  Console.OutputEncoding=Encoding.UTF8; Console.Title="扎根 Grounded Lab 本地服务";
  try {
   string web=Path.Combine(Root,"dist");
   if(!File.Exists(Path.Combine(web,"index.html"))) throw new Exception("未找到 dist 文件夹。");
   bool test=Array.IndexOf(args,"--test-no-browser")>=0;
   string browser=test?null:FindBrowser();
   if(!test&&browser==null)throw new Exception("未找到 Microsoft Edge 或 Google Chrome。");
   var listener=new TcpListener(IPAddress.Loopback,Port);listener.Start();
   string profile=Path.Combine(Root,"用户数据"),temp=Path.Combine(Root,"临时文件");
   Directory.CreateDirectory(profile);Directory.CreateDirectory(temp);
   string downloads=Path.Combine(Root,"导出成果"),defaults=Path.Combine(profile,"Default"),prefs=Path.Combine(defaults,"Preferences");
   Directory.CreateDirectory(downloads);Directory.CreateDirectory(defaults);
   if(!File.Exists(prefs)){var download=new Dictionary<string,object>{{"default_directory",downloads},{"prompt_for_download",false},{"directory_upgrade",true}};File.WriteAllText(prefs,Json().Serialize(new Dictionary<string,object>{{"download",download}}),new UTF8Encoding(false));}
   Environment.SetEnvironmentVariable("TEMP",temp);Environment.SetEnvironmentVariable("TMP",temp);
   ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
   Console.WriteLine("扎根工作台已启动。请保持此窗口开启；关闭窗口将停止服务。");
   Console.WriteLine("http://127.0.0.1:"+Port+"/");
   if(!test){var p=new ProcessStartInfo(browser,"--app=http://127.0.0.1:"+Port+"/ --user-data-dir=\""+profile+"\" --no-first-run --no-default-browser-check");p.UseShellExecute=false;Process.Start(p);}
   while(true){var c=listener.AcceptTcpClient();ThreadPool.QueueUserWorkItem(delegate(object o){Serve((TcpClient)o,web);},c);}
  } catch(SocketException){Console.WriteLine("端口 "+Port+" 已被占用，请关闭已有实例后重试。");}
  catch(Exception e){Console.WriteLine("启动失败："+e.Message);}
  Console.WriteLine("按回车键退出。");Console.ReadLine();
 }
 static string FindBrowser(){
  string[] a={Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),"Microsoft","Edge","Application","msedge.exe"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),"Microsoft","Edge","Application","msedge.exe"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),"Google","Chrome","Application","chrome.exe"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),"Google","Chrome","Application","chrome.exe"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Google","Chrome","Application","chrome.exe")};
  foreach(string p in a)if(File.Exists(p))return p;return null;
 }
 static void Serve(TcpClient client,string web){
  using(client)try{
   client.ReceiveTimeout=15000;client.SendTimeout=180000;
   using(var stream=client.GetStream()){
    string line=ReadLine(stream);if(String.IsNullOrEmpty(line))return;
    var parts=line.Split(' ');if(parts.Length<2)return;
    var headers=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
    string h;int count=0;while(!String.IsNullOrEmpty(h=ReadLine(stream))){if(++count>80||h.Length>8192)throw new Exception("请求头过大");int i=h.IndexOf(':');if(i>0)headers[h.Substring(0,i).Trim()]=h.Substring(i+1).Trim();}
    string host=Get(headers,"Host"),path=parts[1].Split('?')[0];
    if(host!="127.0.0.1:"+Port){Send(stream,403,"text/plain",Encoding.UTF8.GetBytes("Forbidden"));return;}
    if(parts[0]=="POST"&&path=="/api/chat"){
     if(Get(headers,"Origin")!="http://127.0.0.1:"+Port || Get(headers,"X-Grounded-Request")!="1" || !Get(headers,"Content-Type").StartsWith("application/json",StringComparison.OrdinalIgnoreCase)){Send(stream,403,"application/json",Encoding.UTF8.GetBytes("{\"error\":\"Forbidden\"}"));return;}
     int length;if(!Int32.TryParse(Get(headers,"Content-Length"),out length)||length<1||length>MaxBody){Send(stream,413,"application/json",Encoding.UTF8.GetBytes("{\"error\":\"请求过大\"}"));return;}
     byte[] body=new byte[length];int offset=0,n;while(offset<length&&(n=stream.Read(body,offset,length-offset))>0)offset+=n;
     if(offset!=length)throw new Exception("请求不完整");
     HandleChat(stream,Encoding.UTF8.GetString(body));return;
    }
    if(parts[0]!="GET"){Send(stream,405,"text/plain",new byte[0]);return;}
    string name=path=="/"?"index.html":path.TrimStart('/');
    if(name!="index.html"&&name!="app.js"&&name!="core.js"&&name!="seed.js"&&name!="workflow.js"&&name!="styles.css"){Send(stream,404,"text/plain",new byte[0]);return;}
    string mime=name.EndsWith(".html")?"text/html; charset=utf-8":name.EndsWith(".css")?"text/css; charset=utf-8":"text/javascript; charset=utf-8";
    Send(stream,200,mime,File.ReadAllBytes(Path.Combine(web,name)));
   }
  }catch{}
 }
 static string Get(Dictionary<string,string> d,string k){string v;return d.TryGetValue(k,out v)?v:"";}
 static string ReadLine(Stream s){var b=new List<byte>();int x;while((x=s.ReadByte())>=0){if(x==10)break;if(x!=13)b.Add((byte)x);if(b.Count>8192)throw new Exception("请求行过长");}return Encoding.ASCII.GetString(b.ToArray());}
 static void HandleChat(Stream client,string input){
  try{
   var payload=Json().Deserialize<Dictionary<string,object>>(input);
   string endpoint=Convert.ToString(payload["endpoint"]),key=Convert.ToString(payload["key"]),model=Convert.ToString(payload["model"]);
   Uri uri;
   if(!Uri.TryCreate(endpoint,UriKind.Absolute,out uri)||uri.Scheme!="https"||!String.IsNullOrEmpty(uri.UserInfo)||!String.IsNullOrEmpty(uri.Fragment)||!uri.AbsolutePath.TrimEnd('/').EndsWith("/chat/completions"))throw new Exception("接口地址须为 HTTPS 的完整 /chat/completions 地址。");
   if(String.IsNullOrWhiteSpace(key)||key.IndexOfAny(new char[]{'\r','\n'})>=0||String.IsNullOrWhiteSpace(model))throw new Exception("请填写模型和 API Key。");
   var request=(HttpWebRequest)WebRequest.Create(uri);request.Method="POST";request.ContentType="application/json";request.Headers[HttpRequestHeader.Authorization]="Bearer "+key;request.AllowAutoRedirect=false;request.Timeout=180000;request.ReadWriteTimeout=180000;
   var body=new Dictionary<string,object>{{"model",model},{"messages",payload["messages"]},{"stream",false}};
   byte[] bytes=Encoding.UTF8.GetBytes(Json().Serialize(body));request.ContentLength=bytes.Length;
   using(var s=request.GetRequestStream())s.Write(bytes,0,bytes.Length);
   using(var response=(HttpWebResponse)request.GetResponse())using(var sr=new StreamReader(response.GetResponseStream(),Encoding.UTF8)){
    string text=sr.ReadToEnd();if(text.Length>5*1024*1024)throw new Exception("服务返回内容过大。");
    Send(client,200,"application/json; charset=utf-8",Encoding.UTF8.GetBytes(text));
   }
  }catch(WebException e){
   var response=e.Response as HttpWebResponse; string reason=response==null?"网络连接失败或请求超时":("模型服务返回 HTTP "+(int)response.StatusCode);
   if(response!=null)response.Close();Error(client,reason+"。请检查网络、接口地址、模型及密钥。");
  }catch(Exception e){Error(client,e.Message);}
 }
 static void Error(Stream s,string message){Send(s,502,"application/json; charset=utf-8",Encoding.UTF8.GetBytes(Json().Serialize(new Dictionary<string,string>{{"error",message}})));}
 static void Send(Stream s,int code,string mime,byte[] data){
  string status=code==200?"OK":code==403?"Forbidden":code==404?"Not Found":code==405?"Method Not Allowed":code==413?"Payload Too Large":"Bad Gateway";
  byte[] h=Encoding.ASCII.GetBytes("HTTP/1.1 "+code+" "+status+"\r\nContent-Type: "+mime+"\r\nContent-Length: "+data.Length+"\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n");
  s.Write(h,0,h.Length);s.Write(data,0,data.Length);
 }
}