# reyes_assistant.py

from speech import speak
from voice import calibrate_microphone, listen
from wake_word import wait_for_wake_word
from brain import think
from assistant_mode import get_mode


def start():
    print("=" * 50)
    print("REYES AI Assistant")
    print("=" * 50)

    if not calibrate_microphone():
        print("Microphone could not be initialized.")
        return

    if get_mode() == "serious":
        speak("REYES online. Serious mode active.")
    else:
        speak("REYES is online.")

    while True:
        try:
            # Wait until the user says "Hey REYES"
            wait_for_wake_word()

            if get_mode() == "serious":
                speak("Ready.")
            else:
                speak("Yes?")

            while True:
                command = listen()

                if not command:
                    continue

                # Return to standby
                if command in {
                    "sleep",
                    "go to sleep",
                    "standby",
                    "stop listening",
                }:
                    if get_mode() == "serious":
                        speak("Returning to standby.")
                    else:
                        speak("Going back to standby.")
                    break

                # Shutdown
                if command in {
                    "shutdown",
                    "shutdown reyes",
                    "exit",
                    "quit",
                }:
                    if get_mode() == "serious":
                        speak("Shutting down.")
                    else:
                        speak("Goodbye.")

                    return

                response = think(command)

                if response:
                    print(f"REYES: {response}")
                    speak(response)

        except KeyboardInterrupt:
            speak("Shutting down.")
            break

        except Exception as error:
            print(f"[Assistant Error] {error}")
            speak("An unexpected error occurred.")


if __name__ == "__main__":
    start()