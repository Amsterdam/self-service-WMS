## Self-Service WMS
Welkom bij de repository Self-Service WMS!
Deze repository is ontwikkeld om teams binnen de Gemeente Amsterdam te ondersteunen bij het eenvoudig aanmaken van een [WMS](https://mapserver.org/ogc/wms_server.html#wms-server) (Web Map Service) met behulp van een MapFile voor MapServer. Op dit moment ondersteunt de tool alleen zogenaamde "simpele" MapFiles.


### Wat is een Simpele WMS? 
Een simpele WMS voldoet aan de volgende kenmerken:

- Data wordt rechtstreeks opgehaald uit de Ref.DB zonder transformaties.
- Filtering is beperkt tot één kolom:
  - Voor één enkele kaartlaag, **of**
  - Voor meerdere categorieën binnen een kaartlaag.
-  Eén kleur wordt gebruikt voor polygonen of symbolen.
-  Geen complexe symbolen of kleurcombinaties.
- Geen verschillen in weergave op verschillende zoomniveaus.
- Geen combinatie van verschillende laagtypen in één MapFile (bijvoorbeeld punten en polygonen, of gewichten en locaties).
- Labels zijn eenvoudig en worden niet gegenereerd uit complexe queries.


### Hoe werkt het?
Volg de onderstaande stappen om aan de slag te gaan:
1. Maak een lokale clone van deze repository:
  ```
git clone <repository-url>
 ``` 
2. Navigeer naar de lokale map van de repository in je terminal.
3. Installeer de benodigde Python-pakketten:
``` 
pip install -r requirements.txt
```
4. Start de applicatie:
```
py app.py
```
5. Volg de instructies die in de terminal verschijnen.



