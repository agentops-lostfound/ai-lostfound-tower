Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
[ComImport, Guid("29840822-5B84-11D0-BD3B-00A0C911CE86"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface DeviceEnumerator {
 [PreserveSig] int CreateClassEnumerator(ref Guid category, out IEnumMoniker items, int flags);
}
[ComImport, Guid("55272A00-42CB-11CE-8135-00AA004BB851"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface PropertyBag {
 [PreserveSig] int Read([MarshalAs(UnmanagedType.LPWStr)] string key, [In,Out,MarshalAs(UnmanagedType.Struct)] ref object value, IntPtr error);
}
public static class VideoDevices {
 public class Device { public int index; public string name; public string path; }
 public static Device[] List() {
  var devices=new List<Device>();
  var category=new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
  var root=(DeviceEnumerator)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86")));
  IEnumMoniker items;
  if(root.CreateClassEnumerator(ref category,out items,0)==0) {
   var next=new IMoniker[1];
   while(items.Next(1,next,IntPtr.Zero)==0) {
    string display; next[0].GetDisplayName(null,null,out display);
    string name=display;
    try {
     var id=typeof(PropertyBag).GUID; object storage;
     next[0].BindToStorage(null,null,ref id,out storage);
     object value=null;
     if(((PropertyBag)storage).Read("FriendlyName",ref value,IntPtr.Zero)==0)name=Convert.ToString(value);
    } catch(COMException) {}
    devices.Add(new Device {index=devices.Count,name=name,path=display});
   }
  }
  return devices.ToArray();
 }
}
"@
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$devices = foreach ($device in [VideoDevices]::List()) {
    $location = $null
    if ($device.path -match 'usb#([^#]+)#([^#]+)#') {
        $instance = 'USB\'+$Matches[1]+'\'+$Matches[2]
        $property = Get-PnpDeviceProperty -InstanceId $instance -KeyName 'DEVPKEY_Device_LocationPaths' -ErrorAction SilentlyContinue
        $location = @($property.Data)[0]
    }
    [pscustomobject]@{ index=$device.index; name=$device.name; path=$device.path; location=$location }
}
ConvertTo-Json -InputObject @($devices | Where-Object { $_ -ne $null }) -Compress
