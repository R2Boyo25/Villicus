import {html, render, Component, useState} from 'https://esm.sh/htm/preact/standalone'
import {httpGet} from '/static/js/common.mjs'

function BarSegment(props) {
    return html`<div class="barsegment tooltip" style="background-color: ${props.color};">
            <div class="barcontainer">
                <div class="bartext">
                    ${props.percentage}%
                </div>
            </div>
            <div class="tooltiptext">
                ${props.type}
            </div>
        </div>`;
}

class StatusBar extends Component {
    state = {
        running: 0,
        paused: 0,
        killed: 100,
        done: 0
    };

    makeSocket() {
        this.socket = new WebSocket((window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + "/ws/status");
        
        this.socket.addEventListener('message', (event) => {
            this.setState(JSON.parse(event.data));
            this.render();
        });

        this.socket.addEventListener('close', (event) => {
            console.warn("Status websocket disconnected, attempting reconnect...");
            
            setTimeout(this.makeSocket.bind(this), 10000);
        });
    }
    
    constructor() {
        super();

        this.makeSocket();
    }
    
    render() {
        return html`
<${BarSegment} type=Running percentage=${this.state.running} color=darkgreen/>
<${BarSegment} type=Paused percentage=${this.state.paused} color=darkorange/>
<${BarSegment} type="Killed/Exited" percentage=${this.state.killed} color=darkred/>
<${BarSegment} type=Done percentage=${this.state.done} color="rgb(39, 28, 28)"/>
`
        return httpGet("/status");
    }
}

export {StatusBar, html, render}
