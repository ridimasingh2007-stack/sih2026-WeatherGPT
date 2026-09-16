const API_BASE="http://127.0.0.1:8000";let city="Bhopal",token=localStorage.getItem("weatherGPTToken")||"",authMode="login";const $=id=>document.getElementById(id);
function icon(c){if(c===0)return"☀️";if([1,2].includes(c))return"🌤️";if(c===3)return"☁️";if([45,48].includes(c))return"🌫️";if([51,53,55,56,57].includes(c))return"🌦️";if([61,63,65,80,81,82].includes(c))return"🌧️";if([71,73,75,77,85,86].includes(c))return"🌨️";if([95,96,99].includes(c))return"⛈️";return"🌤️"}
function text(c){const n={0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Fog",48:"Rime fog",51:"Light drizzle",53:"Drizzle",55:"Heavy drizzle",61:"Light rain",63:"Rain",65:"Heavy rain",71:"Light snow",73:"Snow",75:"Heavy snow",80:"Rain showers",81:"Rain showers",82:"Heavy rain showers",95:"Thunderstorm",96:"Thunderstorm with hail",99:"Severe thunderstorm"};return n[c]||"Weather"}
async function api(url,opt={}){const r=await fetch(url,{...opt,headers:{"Content-Type":"application/json",...(opt.headers||{}),...(token?{"Authorization":"Bearer "+token}:{})}});if(!r.ok)throw Error((await r.json().catch(()=>({}))).detail||`Request failed (${r.status})`);return r.json()}
async function loadWeather(){ $("locationLabel").textContent=city;$("chatLocation").textContent=city;try{const d=await api(`${API_BASE}/api/weather?location=${encodeURIComponent(city)}`);const w=d.weather||d.current||{};const c=w.weather_code??w.weathercode??0;$("temperature").textContent=Math.round(w.temperature??w.temperature_2m??0);$("feelsLike").textContent=Math.round(w.apparent_temperature??w.feels_like??w.temperature??0);$("condition").textContent=text(c);$("weatherSymbol").textContent=icon(c);$("humidity").textContent=(w.relative_humidity_2m??w.humidity??"--")+"%";$("wind").textContent=Math.round(w.wind_speed_10m??w.wind_speed??0)+" km/h";$("pressure").textContent=Math.round(w.surface_pressure??w.pressure??0)+" hPa";renderForecast(d.forecast||d.daily||{})}catch(e){$("condition").textContent="Couldn't load weather";console.error(e)}}
function renderForecast(f) {
    const a = Array.isArray(f) ? f.slice(0, 7) : [];

    if (a[0]) {
        $("rainChance").textContent =
            (a[0].max_rain_probability ?? 0) + "%";
    }

    const card = x => `
        <div class="day-card">
            <b>${new Date(x.date + "T12:00:00").toLocaleDateString("en", {
                weekday: "short"
            })}</b>

            <div class="icon">${icon(x.weather_code)}</div>

            <strong>
                ${Math.round(x.max_temperature ?? 0)}° /
                ${Math.round(x.min_temperature ?? 0)}°
            </strong>

            <div class="rain">
                💧 ${x.max_rain_probability ?? 0}%
            </div>
        </div>
    `;

    $("forecastPreview").innerHTML = a.map(card).join("");

    $("forecastFull").innerHTML = a.map(x => `
        <div class="day-card">
            <b>${new Date(x.date + "T12:00:00").toLocaleDateString("en", {
                weekday: "long"
            })}</b>

            <div class="icon">${icon(x.weather_code)}</div>

            <div>
                <strong>${text(x.weather_code)}</strong>
                <br>
                <small>${x.date}</small>
            </div>

            <strong>
                ${Math.round(x.max_temperature ?? 0)}° /
                ${Math.round(x.min_temperature ?? 0)}°
            </strong>
        </div>
    `).join("");
}
async function alerts(){try{const d=await api(`${API_BASE}/api/alerts?location=${encodeURIComponent(city)}`),a=d.alerts||[];$("alertsList").innerHTML=a.length?a.map(x=>`<div class="alert"><b>⚠️ ${x.title||x.type||"Weather alert"}</b><p>${x.message||x.description||"Please check local conditions."}</p></div>`).join(""):`<div class="alert"><b>✓ No active alerts</b><p>No threshold-based alerts were detected for ${city}.</p></div>`}catch(e){$("alertsList").innerHTML=`<div class="alert"><b>Unable to load alerts</b><p>${e.message}</p></div>`}}
function msg(box,t,who){const d=document.createElement("div");d.className=who==="user"?"user":"bot";d.textContent=t;box.appendChild(d);box.scrollTop=box.scrollHeight}
async function chat(input,box){const m=input.value.trim();if(!m)return;msg(box,m,"user");input.value="";msg(box,"Thinking…","bot");const wait=box.lastChild;try{if(!token)throw Error("Please log in first to use WeatherGPT chat.");const d=await api(API_BASE+"/api/chat",{method:"POST",body:JSON.stringify({message:m,language:$("language").value,location:city,conversation_id:""})});wait.remove();msg(box,d.answer||d.message||"No answer returned.","bot")}catch(e){wait.textContent=e.message}}
function section(n){document.querySelectorAll(".section").forEach(x=>x.classList.remove("active"));$(n).classList.add("active");document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.section===n));if(n==="alerts")alerts()}
document.querySelectorAll(".nav[data-section]").forEach(x=>x.onclick=()=>section(x.dataset.section));document.querySelectorAll("[data-go]").forEach(x=>x.onclick=()=>section(x.dataset.go));$("searchBtn").onclick=()=>{city=$("cityInput").value.trim()||"Bhopal";loadWeather()};$("cityInput").onkeydown=e=>{if(e.key==="Enter")$("searchBtn").click()};$("sendChat").onclick=()=>chat($("chatInput"),$("chatMessages"));$("chatInput").onkeydown=e=>{if(e.key==="Enter")chat($("chatInput"),$("chatMessages"))};$("fullSendChat").onclick=()=>chat($("fullChatInput"),$("fullChatMessages"));$("fullChatInput").onkeydown=e=>{if(e.key==="Enter")chat($("fullChatInput"),$("fullChatMessages"))};
$("loginBtn").onclick=()=>$("loginModal").classList.remove("hidden");$("closeModal").onclick=()=>$("loginModal").classList.add("hidden");$("switchAuth").onclick=()=>{authMode=authMode==="login"?"register":"login";$("authTitle").textContent=authMode==="login"?"Login":"Create account";$("authSubmit").textContent=authMode==="login"?"Login":"Register";$("authName").classList.toggle("hidden",authMode==="login");$("switchAuth").textContent=authMode==="login"?"New here? Create an account":"Already have an account? Login"};
$("authSubmit").onclick=async()=>{try{const body=authMode==="register"?{name:$("authName").value,email:$("authEmail").value,password:$("authPassword").value}:{email:$("authEmail").value,password:$("authPassword").value};const d=await api(API_BASE+(authMode==="register"?"/api/auth/register":"/api/auth/login"),{method:"POST",body:JSON.stringify(body)});if(d.access_token){token=d.access_token;localStorage.setItem("weatherGPTToken",token)}$("authMessage").textContent=authMode==="login"?"Logged in successfully!":"Account created — now log in."}catch(e){$("authMessage").textContent=e.message}};
const h=new Date().getHours();$("greeting").textContent=(h<12?"Good morning":h<18?"Good afternoon":"Good evening")+" 👋";loadWeather();